"""Event-driven backtesting engine.

This is the core of the platform, and the place where the problem statement's
"Financial Considerations" are answered structurally rather than with a
disclaimer:

* **No look-ahead.** A strategy sees bars up to and including *t* and produces a
  target position for *t*. The engine shifts that target forward one bar and
  fills it at the **open of t+1**. Trading on a close you could not yet have
  observed is therefore impossible by construction, not by convention.
  ``tests/test_engine.py`` asserts it directly.
* **No data leakage.** Every indicator feeding a signal is causal (rolling/ewm
  only), verified by the Phase 2 causality suite.
* **Realistic execution.** Commission and slippage are charged on notional at
  both entry and exit. Slippage always moves the fill against the trade: you buy
  a little higher and sell a little lower than the printed open.
* **Honest benchmark.** Buy-and-hold runs through this same engine and pays the
  same entry cost, so a strategy is never flattered by a frictionless baseline.

The loop is explicit rather than vectorised. It is slower — roughly 15 ms over a
decade of daily bars, far inside budget — but it produces a real trade log whose
arithmetic can be audited line by line, which a vectorised position-times-returns
shortcut cannot.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from ..analytics.metrics import cumulative_returns, drawdown_series, summarise
from ..config import (
    DEFAULT_BORROW_BPS_ANNUAL,
    DEFAULT_COMMISSION_BPS,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_POSITION_PCT,
    DEFAULT_SLIPPAGE_BPS,
    get_asset,
)

BPS = 1e-4


@dataclass(frozen=True)
class BacktestConfig:
    """Execution assumptions. Every field is user-adjustable from the dashboard,
    which is what makes the robustness sweeps in Phase 5 possible."""

    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    commission_bps: float = DEFAULT_COMMISSION_BPS
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS
    position_pct: float = DEFAULT_POSITION_PCT
    allow_short: bool = False
    # Annual cost of borrowing the asset, charged per bar while short. Real
    # shorts are not free: you pay a borrow fee for as long as the position is
    # open. With this at zero a short position could be held for a decade at no
    # cost, which flatters every short-side result.
    borrow_bps_annual: float = DEFAULT_BORROW_BPS_ANNUAL

    def as_dict(self) -> dict:
        return {
            "initial_capital": self.initial_capital,
            "commission_bps": self.commission_bps,
            "slippage_bps": self.slippage_bps,
            "position_pct": self.position_pct,
            "allow_short": self.allow_short,
            "borrow_bps_annual": self.borrow_bps_annual,
        }


@dataclass
class Trade:
    """One round trip. Prices stored here are *fill* prices, inclusive of
    slippage; ``ref_entry``/``ref_exit`` keep the unslipped open so the cost
    breakdown can be reconstructed."""

    entry_date: pd.Timestamp
    entry_price: float
    ref_entry: float
    units: float
    direction: int
    commission: float = 0.0
    slippage: float = 0.0
    borrow: float = 0.0
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    ref_exit: float | None = None
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0
    bars_held: int = 0
    is_open: bool = True

    @property
    def costs(self) -> float:
        return self.commission + self.slippage + self.borrow

    def as_dict(self) -> dict:
        return {
            "entry_date": str(self.entry_date.date()),
            "exit_date": str(self.exit_date.date()) if self.exit_date is not None else None,
            "direction": "long" if self.direction > 0 else "short",
            "units": round(self.units, 8),
            "entry_price": round(self.entry_price, 4),
            "exit_price": round(self.exit_price, 4) if self.exit_price is not None else None,
            "commission": round(self.commission, 2),
            "slippage": round(self.slippage, 2),
            "borrow": round(self.borrow, 2),
            "costs": round(self.costs, 2),
            "gross_pnl": round(self.gross_pnl, 2),
            "net_pnl": round(self.net_pnl, 2),
            "return_pct": round(self.return_pct, 6),
            "bars_held": self.bars_held,
            "is_open": self.is_open,
        }


@dataclass
class BacktestResult:
    asset: str
    strategy: str
    params: dict
    equity: pd.Series
    returns: pd.Series
    position: pd.Series
    signals: pd.Series
    trades: list[Trade] = field(default_factory=list)
    config: BacktestConfig = field(default_factory=BacktestConfig)

    @property
    def ann_factor(self) -> int:
        return get_asset(self.asset).ann_factor

    def stats(self) -> dict:
        """Return/risk block plus the trade statistics the brief asks for."""
        base = summarise(self.returns, self.ann_factor)
        closed = [t for t in self.trades if not t.is_open]
        wins = [t for t in closed if t.net_pnl > 0]
        losses = [t for t in closed if t.net_pnl <= 0]
        won = sum(t.net_pnl for t in wins)
        lost = abs(sum(t.net_pnl for t in losses))

        base.update(
            {
                "initial_capital": self.config.initial_capital,
                "final_equity": float(self.equity.iloc[-1]) if len(self.equity) else self.config.initial_capital,
                "num_trades": len(closed),
                "num_open_trades": len(self.trades) - len(closed),
                "win_rate": len(wins) / len(closed) if closed else 0.0,
                "avg_win": won / len(wins) if wins else 0.0,
                "avg_loss": -lost / len(losses) if losses else 0.0,
                "profit_factor": (won / lost) if lost > 0 else (float("inf") if won > 0 else 0.0),
                "total_commission": sum(t.commission for t in self.trades),
                "total_slippage": sum(t.slippage for t in self.trades),
                "total_borrow": sum(t.borrow for t in self.trades),
                "total_costs": sum(t.costs for t in self.trades),
                "avg_bars_held": float(np.mean([t.bars_held for t in closed])) if closed else 0.0,
                "exposure": float((self.position != 0).mean()) if len(self.position) else 0.0,
            }
        )
        return base

    def curves(self) -> dict:
        """JSON-ready series for the dashboard."""
        cum = cumulative_returns(self.returns).reindex(self.equity.index).fillna(0.0)
        dd = drawdown_series(self.returns).reindex(self.equity.index).fillna(0.0)
        return {
            "dates": [str(d.date()) for d in self.equity.index],
            "equity": [round(float(v), 2) for v in self.equity.to_numpy()],
            "cumulative_return": [round(float(v), 6) for v in cum.to_numpy()],
            "drawdown": [round(float(v), 6) for v in dd.to_numpy()],
            "position": [int(v) for v in self.position.to_numpy()],
        }

    def trade_log(self) -> list[dict]:
        return [t.as_dict() for t in self.trades]


def run_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    asset: str,
    strategy: str = "custom",
    params: dict | None = None,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Simulate ``signals`` on ``df``.

    ``signals`` holds the *target* position for each bar in ``{-1, 0, 1}``,
    computed from information available at that bar's close. The engine lags it
    by one bar and executes at the next open.
    """
    cfg = config or BacktestConfig()
    params = params or {}

    data = df.dropna(subset=["open", "close"])
    if data.empty:
        raise ValueError(f"{asset}: no usable bars to backtest")

    raw_signals = signals.reindex(data.index).fillna(0.0)
    if not cfg.allow_short:
        raw_signals = raw_signals.clip(lower=0)

    # --- THE bias guard: decide on bar t, act on bar t+1 -------------------
    target = raw_signals.shift(1).fillna(0.0)

    opens = data["open"].to_numpy(dtype="float64")
    closes = data["close"].to_numpy(dtype="float64")
    dates = data.index
    tgt = np.sign(target.to_numpy(dtype="float64")).astype(int)

    comm_rate = cfg.commission_bps * BPS
    slip_rate = cfg.slippage_bps * BPS
    # Per-bar borrow rate, de-annualised with the asset's own calendar so a
    # crypto short (365 bars/year) is not charged an equity year's worth.
    borrow_rate = (cfg.borrow_bps_annual * BPS) / get_asset(asset).ann_factor

    cash = float(cfg.initial_capital)
    units = 0.0          # unsigned size of the open position
    direction = 0        # -1, 0, +1
    entry_bar = 0
    open_trade: Trade | None = None

    equity_curve = np.empty(len(data), dtype="float64")
    position_curve = np.zeros(len(data), dtype="float64")
    trades: list[Trade] = []

    for i in range(len(data)):
        desired = int(tgt[i])
        ref = opens[i]

        if desired != direction:
            # ---- close the existing position first -----------------------
            if direction != 0 and open_trade is not None:
                # Selling a long fills below the open; buying back a short
                # fills above it. Slippage never helps.
                fill = ref * (1 - slip_rate) if direction > 0 else ref * (1 + slip_rate)
                notional = units * fill
                commission = notional * comm_rate

                # Signed accounting handles both directions in one expression:
                # a long receives +units*fill, a short pays it back.
                cash += direction * units * fill - commission

                open_trade.exit_date = dates[i]
                open_trade.exit_price = fill
                open_trade.ref_exit = ref
                open_trade.commission += commission
                open_trade.slippage += units * slip_rate * ref
                open_trade.gross_pnl = direction * units * (ref - open_trade.ref_entry)
                open_trade.net_pnl = open_trade.gross_pnl - open_trade.costs
                basis = units * open_trade.ref_entry
                open_trade.return_pct = open_trade.net_pnl / basis if basis else 0.0
                open_trade.bars_held = i - entry_bar
                open_trade.is_open = False
                trades.append(open_trade)

                open_trade = None
                units = 0.0
                direction = 0

            # ---- open the new one ---------------------------------------
            if desired != 0:
                fill = ref * (1 + slip_rate) if desired > 0 else ref * (1 - slip_rate)
                budget = cash * cfg.position_pct
                size = budget / (fill * (1 + comm_rate)) if fill > 0 else 0.0
                if size > 0:
                    commission = size * fill * comm_rate
                    # Long: pay out notional. Short: receive it.
                    cash -= desired * size * fill
                    cash -= commission

                    units = size
                    direction = desired
                    entry_bar = i
                    open_trade = Trade(
                        entry_date=dates[i],
                        entry_price=fill,
                        ref_entry=ref,
                        units=size,
                        direction=desired,
                        commission=commission,
                        slippage=size * slip_rate * ref,
                    )

        # ---- carry cost of an open short ---------------------------------
        # Charged on the position's current notional, every bar it is held.
        if direction < 0 and open_trade is not None and borrow_rate > 0:
            fee = units * closes[i] * borrow_rate
            cash -= fee
            open_trade.borrow += fee

        # ---- mark to market at this bar's close --------------------------
        equity_curve[i] = cash + direction * units * closes[i]
        position_curve[i] = direction

    equity = pd.Series(equity_curve, index=dates, name="equity")
    returns = equity.pct_change().fillna(0.0)

    # A position still open at the end is marked to market and reported as open
    # rather than silently force-closed at a price the strategy never chose.
    if open_trade is not None:
        open_trade.bars_held = len(data) - 1 - entry_bar
        open_trade.gross_pnl = direction * units * (closes[-1] - open_trade.ref_entry)
        open_trade.net_pnl = open_trade.gross_pnl - open_trade.costs
        basis = units * open_trade.ref_entry
        open_trade.return_pct = open_trade.net_pnl / basis if basis else 0.0
        trades.append(open_trade)

    return BacktestResult(
        asset=get_asset(asset).key,
        strategy=strategy,
        params=params,
        equity=equity,
        returns=returns,
        position=pd.Series(position_curve, index=dates, name="position"),
        signals=raw_signals,
        trades=trades,
        config=cfg,
    )


def buy_and_hold(df: pd.DataFrame, asset: str, config: BacktestConfig | None = None) -> BacktestResult:
    """Benchmark: enter on the first tradable bar and hold to the end.

    Run through the same engine as every strategy, so it pays the same entry
    commission and slippage. Comparing a costed strategy against a frictionless
    benchmark would quietly understate the strategy.

    **Always fully invested**, regardless of the strategy's ``position_pct``.
    Buy-and-hold means putting your capital in the asset and leaving it there;
    a half-sized version is a 50/50 asset-and-cash portfolio, which is a
    different thing wearing the same name. More importantly, a benchmark that
    moves when you change a *strategy* setting is not a reference point — you
    could halve your position size and the strategy would look no worse,
    because the yardstick shrank with it.

    Costs still come from the caller's config, so the like-for-like cost
    treatment the comparison depends on is preserved.
    """
    cfg = config or BacktestConfig()
    if cfg.position_pct != 1.0:
        cfg = replace(cfg, position_pct=1.0)
    signals = pd.Series(1.0, index=df.index)
    return run_backtest(df, signals, asset, strategy="buy_and_hold", config=cfg)
