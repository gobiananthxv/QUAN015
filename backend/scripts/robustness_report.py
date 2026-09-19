"""Phase 5 verification: robustness sweeps and regime attribution.

    .venv/bin/python scripts/robustness_report.py          (macOS / Linux)
    .venv/Scripts/python.exe scripts/robustness_report.py  (Windows)

Answers the two questions a single backtest number cannot:
  * does the result survive changing the parameters, the costs, and the period?
  * in which market regimes does the strategy actually earn its keep?

It also audits the confirmation-band defaults introduced in Phase 4, which were
chosen as round numbers rather than fitted. This is where that claim gets tested.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app.backtest.engine import BacktestConfig
from app.backtest.robustness import (
    cost_sweep,
    parameter_sweep,
    period_sweep,
    plateau_report,
    regime_attribution,
    sharpe_surface,
)
from app.config import ASSETS

CFG = BacktestConfig(initial_capital=100_000.0, commission_bps=10.0, slippage_bps=5.0)

# Grids span a wide, round range on each side of the default. Deliberately not
# narrowed around anything that performed well.
GRIDS = {
    "sma_crossover": {"fast": [10, 20, 30, 50, 80, 100], "slow": [100, 150, 200, 250]},
    "ema_trend": {"span": [20, 35, 50, 75, 100], "band": [0.0, 0.005, 0.01, 0.02, 0.03]},
    "momentum": {"window": [30, 60, 90, 120, 180], "band": [0.0, 0.025, 0.05, 0.10, 0.15]},
    "mean_reversion": {"window": [10, 15, 20, 30, 40], "entry_z": [1.0, 1.5, 2.0, 2.5, 3.0]},
}
AXES = {
    "sma_crossover": ("fast", "slow"),
    "ema_trend": ("span", "band"),
    "momentum": ("window", "band"),
    "mean_reversion": ("window", "entry_z"),
}
DEFAULT_BAND = {"ema_trend": 0.01, "momentum": 0.05}


def main() -> int:
    warnings: list[str] = []

    print("=" * 100)
    print("PHASE 5 - ROBUSTNESS & REGIME ATTRIBUTION")
    print("=" * 100)

    # ------------------------------------------------ parameter surfaces
    for name, grid in GRIDS.items():
        x, y = AXES[name]
        print(f"\n{'=' * 100}\nPARAMETER SURFACE - {name}   (Sharpe, {x} x {y})\n{'=' * 100}")

        for key in ASSETS:
            sweep = parameter_sweep(key, name, grid, config=CFG)
            report = plateau_report(sweep, [x, y])
            surface = sharpe_surface(sweep, x, y)

            print(f"\n  {key}")
            print("        " + "".join(f"{c:>8}" for c in surface.columns))
            for idx in surface.index:
                cells = "".join(
                    "     ---" if np.isnan(surface.loc[idx, c]) else f"{surface.loc[idx, c]:>8.2f}"
                    for c in surface.columns
                )
                print(f"  {idx:>6}{cells}")
            print(
                f"        best {report['best']:.2f} at {report['best_params']} | "
                f"median {report['median']:.2f} | worst {report['worst']:.2f} | "
                f"{report['share_positive']:.0%} positive"
            )
            rob = "n/a " if report["robustness"] is None else f"{report['robustness']:.2f}"
            nb = "n/a " if report["best_vs_neighbours"] is None else f"{report['best_vs_neighbours']:.2f}"
            print(f"        robustness {rob} | neighbours {nb} -> {report['verdict']}")

            if report["combinations"] < 2:
                warnings.append(f"{key}/{name}: sweep produced too few cells to judge")

    # ------------------------------------------------ band audit
    print(f"\n\n{'=' * 100}")
    print("CONFIRMATION-BAND AUDIT")
    print("Phase 4 set these defaults as round numbers, NOT fitted to results.")
    print("A default that is not the best cell is evidence the claim is honest.")
    print("=" * 100)

    for name, default in DEFAULT_BAND.items():
        x, y = AXES[name]
        print(f"\n  {name}  (default band = {default})")
        print(f"    {'ASSET':7}{'BEST BAND':>11}{'BEST SHARPE':>13}{'DEFAULT SHARPE':>16}{'GAP':>8}{'RANK':>8}")
        for key in ASSETS:
            sweep = parameter_sweep(key, name, GRIDS[name], config=CFG)
            by_band = sweep.groupby("band")["sharpe"].max().sort_values(ascending=False)
            best_band = by_band.index[0]
            default_sharpe = by_band.get(default, float("nan"))
            rank = list(by_band.index).index(default) + 1
            print(
                f"    {key:7}{best_band:>11.3f}{by_band.iloc[0]:>13.2f}"
                f"{default_sharpe:>16.2f}{by_band.iloc[0] - default_sharpe:>8.2f}"
                f"{rank:>5}/{len(by_band)}"
            )

    # ------------------------------------------------ cost sensitivity
    print(f"\n\n{'=' * 100}\nCOST SENSITIVITY  (bps per side; slippage = half of commission)\n{'=' * 100}")
    for key in ASSETS:
        print(f"\n  {key}")
        print(f"    {'STRATEGY':16}" + "".join(f"{b:>10.0f}" for b in (0, 5, 10, 25, 50, 100)))
        for name in GRIDS:
            sweep = cost_sweep(key, name, config=CFG)
            cells = "".join(f"{r * 100:>9.0f}%" for r in sweep["total_return"])
            print(f"    {name:16}{cells}")
            if not sweep["total_return"].is_monotonic_decreasing:
                warnings.append(f"{key}/{name}: return did not fall monotonically with costs")

    # ------------------------------------------------ period stability
    print("\n\n" + "=" * 100)
    print("PERIOD STABILITY  (5 consecutive windows, GEOMETRIC excess vs buy-and-hold)")
    print("Geometric, not arithmetic: subtracting two compounded returns is unreadable")
    print("once they are large. -70% here means the strategy ended with 30% of the")
    print("benchmark's wealth. The arithmetic figure for that same window reads -639%.")
    print("=" * 100)
    for key in ASSETS:
        print(f"\n  {key}")
        for name in GRIDS:
            windows = period_sweep(key, name, n_windows=5, config=CFG)
            cells = "".join(f"{v * 100:>+10.0f}%" for v in windows["relative_return"])
            beat = int((windows["excess_return"] > 0).sum())
            print(f"    {name:16}{cells}   beat {beat}/{len(windows)}")
            if windows["bars"].sum() == 0:
                warnings.append(f"{key}/{name}: period sweep produced no bars")

    # ------------------------------------------------ regime attribution
    print(f"\n\n{'=' * 100}\nREGIME ATTRIBUTION  (strategy vs benchmark, by market regime; EXCESS is geometric)\n{'=' * 100}")
    for key in ASSETS:
        for name in GRIDS:
            rows = regime_attribution(key, name, config=CFG)
            print(f"\n  {key} / {name}")
            print(
                f"    {'AXIS':11}{'REGIME':12}{'DAYS':>6}{'EXPOS':>7}"
                f"{'STRATEGY':>12}{'BENCHMARK':>12}{'EXCESS':>12}{'BEAT':>6}"
            )
            for r in rows:
                print(
                    f"    {r['axis']:11}{r['regime']:12}{r['days']:>6}{r['exposure']:>6.0%}"
                    f"{r['strategy_return'] * 100:>11.1f}%{r['benchmark_return'] * 100:>11.1f}%"
                    f"{r['relative_return'] * 100:>11.1f}%{'yes' if r['beat_benchmark'] else 'no':>6}"
                )
            for axis in ("trend", "volatility"):
                share = sum(r["share_of_period"] for r in rows if r["axis"] == axis)
                if abs(share - 1.0) > 1e-6:
                    warnings.append(f"{key}/{name}: {axis} shares sum to {share:.4f}")

    print("\n" + "=" * 100)
    if warnings:
        print(f"PHASE 5 - {len(warnings)} INVARIANT FAILURE(S):")
        for w in warnings:
            print(f"  ! {w}")
        return 1
    print("PHASE 5 PASSED - surfaces, cost/period sweeps and regime attribution all consistent.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
