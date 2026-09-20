"""
forecast_regime.py — Standalone CLI for future regime prediction.

Detects the current market regime using HMM, then forecasts how the
regime probabilities evolve over the next N trading days, computes the
prediction horizon, and generates the 4-panel forecast chart.

Usage
-----
    python forecast_regime.py                                # SPY, 60-day forecast
    python forecast_regime.py --ticker QQQ --days 90
    python forecast_regime.py --ticker SPY --days 120 --paths 1000 --show
    python forecast_regime.py --ticker AAPL --n-states 3 --days 60
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

BOLD  = "\033[1m"
GREEN = "\033[92m"
CYAN  = "\033[96m"
RESET = "\033[0m"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Predict future market regimes using HMM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--ticker",     default="SPY",        help="Ticker symbol (default: SPY)")
    p.add_argument("--start",      default="2010-01-01", help="Training data start date")
    p.add_argument("--end",        default=None,         help="Training data end date (default: today)")
    p.add_argument("--days",       default=60,  type=int, help="Days to forecast ahead (default: 60)")
    p.add_argument("--paths",      default=500, type=int, help="Monte Carlo paths (default: 500)")
    p.add_argument("--n-states",   default=None, type=int, dest="n_states",
                   help="Fix HMM states (default: auto via BIC)")
    p.add_argument("--output-dir", default="output", dest="output_dir",
                   help="Directory for CSV + PNG output (default: ./output/)")
    p.add_argument("--show",       action="store_true",
                   help="Open interactive plot window")
    p.add_argument("--force-download", action="store_true", dest="force_download",
                   help="Re-download data ignoring cache")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logger = logging.getLogger("forecast_regime")

    out = Path(args.output_dir)
    (out / "plots").mkdir(parents=True, exist_ok=True)

    ticker = args.ticker.upper()

    print(f"\n{BOLD}{'═' * 60}")
    print(f"  Future Regime Forecast")
    print(f"  Ticker: {ticker}  |  Horizon: {args.days} trading days")
    print(f"{'═' * 60}{RESET}\n")

    # ── Step 1: Detect current regime ────────────────────────────────────────
    print(f"{CYAN}[1/4] Detecting current regime (HMM) …{RESET}")
    from regime.detector import RegimeDetector
    detector = RegimeDetector(ticker=ticker, model_type="hmm", n_components=args.n_states)
    result   = detector.run(start=args.start, end=args.end, force_download=args.force_download)
    print(result.summary())

    # ── Step 2: Forecast ─────────────────────────────────────────────────────
    print(f"\n{CYAN}[2/4] Computing future regime probabilities …{RESET}")
    from forecast.regime_forecaster import RegimeForecaster
    forecaster   = RegimeForecaster(result)
    forecast_df  = forecaster.forecast(n_steps=args.days)
    decay_df     = forecaster.confidence_decay(n_steps=args.days)
    stat_dist    = forecaster.stationary_distribution()
    horizon      = forecaster.prediction_horizon(n_steps=args.days * 2)

    # ── Step 3: Print table ───────────────────────────────────────────────────
    print(f"\n{CYAN}[3/4] Forecast table{RESET}")
    print(f"\n  {BOLD}Regime probabilities — next {args.days} trading days{RESET}")
    cols = list(forecast_df.columns)
    header = f"  {'Day':>5}  " + "  ".join(f"{c:>17}" for c in cols)
    print(header)
    print("  " + "─" * len(header))

    key_days = sorted(set(
        [1, 2, 3, 5, 10, 15, 21, 30, 42, 60, 90, 120]
        + [args.days]
    ))
    for day in key_days:
        if day <= args.days:
            row = forecast_df.loc[day]
            top = row.idxmax()
            vals = "  ".join(f"{v:>16.1%}" for v in row)
            marker = " ◀" if day == 1 else ""
            conf_flag = "✓" if decay_df.loc[day, "is_useful"] else "✗"
            print(f"  {day:>5}  {vals}  [{conf_flag}]{marker}")

    print("  " + "─" * len(header))
    stat_vals = "  ".join(f"{stat_dist.get(c, 0):>16.1%}" for c in cols)
    print(f"  {'∞':>5}  {stat_vals}   ← long-run stationary")

    print(f"\n  Confidence key:  ✓ = prediction is informative  ✗ = near stationary")

    print(f"\n  {BOLD}Prediction Horizon:{RESET}")
    print(f"    Conservative    : {BOLD}~{horizon['conservative']} trading days{RESET}"
          f"  (≈{horizon['conservative']//5} weeks / ≈{horizon['conservative']//21} months)")
    print(f"    Max-prob based  : ~{horizon['max_prob_horizon']} trading days")
    print(f"    KL-div based    : ~{horizon['kl_horizon']} trading days")
    print()
    print(f"  → Within {horizon['conservative']} days: HMM carries predictive signal")
    print(f"  → Beyond {horizon['conservative']} days: forecast converges to base rates above (↑)")

    # ── Step 4: Export + Plot ─────────────────────────────────────────────────
    print(f"\n{CYAN}[4/4] Exporting results and generating charts …{RESET}")

    forecast_csv = out / f"{ticker}_forecast_{args.days}d.csv"
    forecast_df.to_csv(forecast_csv)
    print(f"  {GREEN}✔{RESET}  Forecast CSV → {forecast_csv}")

    decay_csv = out / f"{ticker}_confidence_decay_{args.days}d.csv"
    decay_df.to_csv(decay_csv)
    print(f"  {GREEN}✔{RESET}  Confidence decay CSV → {decay_csv}")

    import matplotlib
    if not args.show:
        matplotlib.use("Agg")

    save_path = str(out / "plots" / f"{ticker}_forecast_{args.days}d.png")
    forecaster.plot(
        n_steps=args.days,
        n_paths=args.paths,
        save_path=save_path,
        show=args.show,
    )
    print(f"  {GREEN}✔{RESET}  Forecast chart → {save_path}")

    print(f"\n{BOLD}Done.{RESET}\n")


if __name__ == "__main__":
    main()
