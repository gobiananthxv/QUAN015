"""Phase 4 verification: run all four strategies on all three assets.

    .venv/Scripts/python.exe scripts/strategy_report.py

This is the strategy-vs-benchmark comparison the problem statement asks for,
run end to end through the real engine with real costs.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app.backtest.engine import BacktestConfig, buy_and_hold, run_backtest
from app.backtest.strategies import REGISTRY, get_strategy, list_strategies
from app.config import ASSETS
from app.data.store import load_asset


def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def main() -> int:
    warnings: list[str] = []
    cfg = BacktestConfig(initial_capital=100_000.0, commission_bps=10.0, slippage_bps=5.0)

    print("=" * 100)
    print("PHASE 4 - STRATEGY COMPARISON")
    print(
        f"capital ${cfg.initial_capital:,.0f} | commission {cfg.commission_bps:.0f} bps | "
        f"slippage {cfg.slippage_bps:.0f} bps | sizing {cfg.position_pct:.0%}"
    )
    print("=" * 100)

    print("\nAVAILABLE STRATEGIES\n")
    for entry in list_strategies():
        params = ", ".join(f"{k}={v}" for k, v in entry["defaults"].items())
        print(f"  {entry['label']:16} ({entry['name']})")
        print(f"      {entry['description']}")
        print(f"      defaults: {params}\n")

    hdr = (
        f"  {'STRATEGY':16}{'TOTAL':>12}{'CAGR':>9}{'VOL':>9}{'SHARPE':>8}{'SORTINO':>9}"
        f"{'MAXDD':>9}{'TRADES':>8}{'WIN%':>7}{'EXPOS':>7}{'COSTS':>11}"
    )

    for key in ASSETS:
        df = load_asset(key)
        print("\n" + "=" * 100)
        print(f"{key}  ({ASSETS[key].name}, {len(df):,} bars)")
        print("=" * 100)
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))

        bench = buy_and_hold(df, key, config=cfg)
        rows = []

        for name in REGISTRY:
            strat = get_strategy(name)
            signals = strat.generate_signals(df)
            res = run_backtest(df, signals, key, strategy=name, params=strat.params, config=cfg)
            rows.append((strat.label, res))

            s = res.stats()
            # Invariants that must hold for every strategy on every asset.
            net = sum(t.net_pnl for t in res.trades)
            if abs(s["final_equity"] - (cfg.initial_capital + net)) > 1.0:
                warnings.append(f"{key}/{name}: equity curve disagrees with trade log")
            if (res.equity <= 0).any():
                warnings.append(f"{key}/{name}: equity went non-positive")
            expected = np.concatenate([[0], np.sign(res.signals.to_numpy()[:-1])])
            if not np.array_equal(res.position.to_numpy(), expected):
                warnings.append(f"{key}/{name}: execution lag is not exactly one bar")
            if s["num_trades"] == 0 and s["num_open_trades"] == 0:
                warnings.append(f"{key}/{name}: never traded")

        rows.append(("Buy & Hold", bench))

        for label, res in rows:
            s = res.stats()
            sortino = "     inf" if s["sortino"] == float("inf") else f"{s['sortino']:>8.2f}"
            print(
                f"  {label:16}{pct(s['total_return']):>12}{pct(s['cagr']):>9}"
                f"{pct(s['volatility']):>9}{s['sharpe']:>8.2f}{sortino}"
                f"{pct(s['max_drawdown']):>9}{s['num_trades']:>8}"
                f"{s['win_rate'] * 100:>6.1f}%{s['exposure']:>6.0%}{s['total_costs']:>11,.0f}"
            )

        # Rank against the benchmark on the two axes that matter.
        bench_stats = bench.stats()
        beat_return = [l for l, r in rows[:-1] if r.stats()["total_return"] > bench_stats["total_return"]]
        beat_dd = [l for l, r in rows[:-1] if r.stats()["max_drawdown"] > bench_stats["max_drawdown"]]
        beat_sharpe = [l for l, r in rows[:-1] if r.stats()["sharpe"] > bench_stats["sharpe"]]
        print(f"\n    beat benchmark on return : {', '.join(beat_return) or 'none'}")
        print(f"    beat benchmark on Sharpe : {', '.join(beat_sharpe) or 'none'}")
        print(f"    shallower drawdown       : {', '.join(beat_dd) or 'none'}")

    print("\n" + "=" * 100)
    if warnings:
        print(f"PHASE 4 - {len(warnings)} INVARIANT FAILURE(S):")
        for w in warnings:
            print(f"  ! {w}")
        return 1
    print("PHASE 4 PASSED - all 4 strategies ran on all 3 assets; every invariant held.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
