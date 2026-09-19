"""Phase 3 verification: exercise the engine on real data and print the result.

    .venv/Scripts/python.exe scripts/backtest_report.py

Unit tests prove the arithmetic. This proves the engine behaves sensibly on a
decade of real prices, and that its two independent accounts — the equity curve
and the trade log — agree with each other.

Strategies arrive in Phase 4; this drives the engine with simple mechanical
signals so the execution model can be judged on its own.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from app.analytics.indicators import sma
from app.backtest.engine import BacktestConfig, buy_and_hold, run_backtest
from app.config import ASSETS
from app.data.store import load_asset


def pct(x: float) -> str:
    return f"{x * 100:>8.2f}%"


def num(x: float) -> str:
    if x in (float("inf"), float("-inf")):
        return "     inf"
    return f"{x:>8.2f}"


def crossover_signals(close: pd.Series, fast: int = 50, slow: int = 200) -> pd.Series:
    """A placeholder SMA crossover. Phase 4 replaces this with real strategies."""
    f, s = sma(close, fast), sma(close, slow)
    return (f > s).astype(float).where(f.notna() & s.notna(), 0.0)


def main() -> int:
    warnings: list[str] = []
    cfg = BacktestConfig(initial_capital=100_000.0, commission_bps=10.0, slippage_bps=5.0)

    print("=" * 96)
    print("PHASE 3 - BACKTESTING ENGINE")
    print(
        f"capital ${cfg.initial_capital:,.0f} | commission {cfg.commission_bps:.0f} bps | "
        f"slippage {cfg.slippage_bps:.0f} bps | sizing {cfg.position_pct:.0%} of equity"
    )
    print("=" * 96)

    hdr = (
        f"{'ASSET':6}{'RUN':14}{'TOTAL':>11}{'CAGR':>10}{'VOL':>10}{'SHARPE':>9}"
        f"{'MAXDD':>10}{'TRADES':>8}{'WIN%':>8}{'COSTS':>12}{'EXPOS':>8}"
    )

    for key in ASSETS:
        df = load_asset(key)

        t0 = time.perf_counter()
        strat = run_backtest(
            df, crossover_signals(df["close"]), key, strategy="sma_50_200", config=cfg
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        bench = buy_and_hold(df, key, config=cfg)

        print(f"\n{key} - {len(df):,} bars, engine ran in {elapsed_ms:.1f} ms")
        print(hdr)
        print("-" * len(hdr))

        for label, res in (("sma_50_200", strat), ("buy_and_hold", bench)):
            s = res.stats()
            print(
                f"{key:6}{label:14}{pct(s['total_return']):>11}{pct(s['cagr']):>10}"
                f"{pct(s['volatility']):>10}{num(s['sharpe'])}{pct(s['max_drawdown']):>10}"
                f"{s['num_trades']:>8}{s['win_rate'] * 100:>7.1f}%"
                f"{s['total_costs']:>12,.0f}{s['exposure']:>7.0%}"
            )

            # --- invariants the engine must satisfy on any real run ---------
            net = sum(t.net_pnl for t in res.trades)
            if abs(s["final_equity"] - (cfg.initial_capital + net)) > 1.0:
                warnings.append(
                    f"{key}/{label}: equity curve ${s['final_equity']:,.2f} disagrees with "
                    f"trade log ${cfg.initial_capital + net:,.2f}"
                )
            if abs(s["total_costs"] - (s["total_commission"] + s["total_slippage"])) > 1e-6:
                warnings.append(f"{key}/{label}: cost breakdown does not sum")
            if (res.equity <= 0).any():
                warnings.append(f"{key}/{label}: equity went non-positive")
            if s["total_costs"] <= 0:
                warnings.append(f"{key}/{label}: no costs charged despite non-zero bps")
            if not -1.0 < s["max_drawdown"] <= 0.0:
                warnings.append(f"{key}/{label}: max drawdown {s['max_drawdown']:.3f} out of range")

        # Lag is what makes the run honest; assert it on real data too.
        expected = np.concatenate([[0], np.sign(strat.signals.to_numpy()[:-1])])
        if not np.array_equal(strat.position.to_numpy(), expected):
            warnings.append(f"{key}: execution lag is not exactly one bar")

        sample = [t for t in strat.trades if not t.is_open][:3]
        if sample:
            print(f"\n  first {len(sample)} closed trades:")
            print(
                f"    {'ENTRY':12}{'EXIT':12}{'UNITS':>12}{'IN':>10}{'OUT':>10}"
                f"{'GROSS':>12}{'COSTS':>10}{'NET':>12}{'RET':>9}{'BARS':>6}"
            )
            for t in sample:
                d = t.as_dict()
                print(
                    f"    {d['entry_date']:12}{str(d['exit_date']):12}{d['units']:>12.4f}"
                    f"{d['entry_price']:>10.2f}{d['exit_price']:>10.2f}"
                    f"{d['gross_pnl']:>12,.0f}{d['costs']:>10,.0f}{d['net_pnl']:>12,.0f}"
                    f"{d['return_pct'] * 100:>8.2f}%{d['bars_held']:>6}"
                )

    # ---------------------------------------------------------- cost sweep
    print("\n" + "=" * 96)
    print("COST SENSITIVITY - same signals, rising friction (NVDA)")
    print("=" * 96)
    df = load_asset("NVDA")
    signals = crossover_signals(df["close"])
    print(f"\n  {'BPS/SIDE':>10}{'TOTAL':>12}{'SHARPE':>10}{'COSTS PAID':>14}")
    prev = None
    for bps in (0.0, 5.0, 10.0, 25.0, 50.0, 100.0):
        s = run_backtest(
            df, signals, "NVDA",
            config=BacktestConfig(initial_capital=100_000.0, commission_bps=bps, slippage_bps=bps),
        ).stats()
        print(f"  {bps:>10.0f}{s['total_return'] * 100:>11.1f}%{s['sharpe']:>10.2f}{s['total_costs']:>14,.0f}")
        if prev is not None and s["total_return"] >= prev:
            warnings.append(f"NVDA: return did not fall when costs rose to {bps} bps")
        prev = s["total_return"]

    print("\n" + "=" * 96)
    if warnings:
        print(f"PHASE 3 - {len(warnings)} INVARIANT FAILURE(S):")
        for w in warnings:
            print(f"  ! {w}")
        return 1
    print("PHASE 3 PASSED - equity curve and trade log agree; costs and lag verified.")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
