"""
main.py — CLI entry point for the ML-Based Market Regime Detection system.

Usage examples
--------------
# Detect regimes (HMM, default SPY, 2010–today):
    python main.py --ticker SPY --model hmm --start-date 2010-01-01 --plot

# Compare HMM and GMM side by side:
    python main.py --ticker QQQ --model both --plot

# Run walk-forward backtest:
    python main.py --ticker SPY --model hmm --backtest --start-date 2010-01-01

# Fix 3 states, export regime CSV:
    python main.py --ticker AAPL --model gmm --n-states 3 --export regimes.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Bootstrap sys.path so we can import sibling packages
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from config import DEFAULT_TICKER, DEFAULT_START_DATE
from regime.detector import RegimeDetector
from strategy.adaptive_strategy import AdaptiveStrategy
from backtest.walk_forward import WalkForwardBacktest


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ML-Based Market Regime Detection using HMM and GMM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--ticker", default=DEFAULT_TICKER,
        help="Yahoo Finance ticker symbol (default: %(default)s)",
    )
    parser.add_argument(
        "--model", choices=["hmm", "gmm", "both"], default="hmm",
        help="Regime model to use (default: %(default)s)",
    )
    parser.add_argument(
        "--start-date", default=DEFAULT_START_DATE, dest="start_date",
        help="Start date YYYY-MM-DD (default: %(default)s)",
    )
    parser.add_argument(
        "--end-date", default=None, dest="end_date",
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--n-states", type=int, default=None, dest="n_states",
        help="Fix number of hidden states (default: auto-select via BIC)",
    )
    parser.add_argument(
        "--plot", action="store_true",
        help="Show the four-panel regime dashboard",
    )
    parser.add_argument(
        "--save-plots", default=None, dest="save_plots",
        help="Directory to save plots as PNG (skips interactive display)",
    )
    parser.add_argument(
        "--backtest", action="store_true",
        help="Run walk-forward backtesting",
    )
    parser.add_argument(
        "--export", default=None, metavar="FILE.csv",
        help="Export regime series to CSV",
    )
    parser.add_argument(
        "--force-download", action="store_true", dest="force_download",
        help="Re-download data ignoring cache",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_detection(
    ticker: str,
    model_type: str,
    start_date: str,
    end_date,
    n_states,
    force_download: bool,
):
    """Run regime detection for one model type and return the result."""
    detector = RegimeDetector(
        ticker=ticker,
        model_type=model_type,
        n_components=n_states,
    )
    result = detector.run(
        start=start_date,
        end=end_date,
        force_download=force_download,
    )
    return result


def run_backtest(
    ticker: str,
    model_type: str,
    start_date: str,
    end_date,
    n_states,
    force_download: bool,
):
    """Run walk-forward backtest for one model type and return the result."""
    bt = WalkForwardBacktest(
        ticker=ticker,
        model_type=model_type,
        n_components=n_states,
    )
    return bt.run(start=start_date, end=end_date, force_download=force_download)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    _setup_logging(args.verbose)
    logger = logging.getLogger("main")

    model_types = ["hmm", "gmm"] if args.model == "both" else [args.model]
    strategy = AdaptiveStrategy()

    for model_type in model_types:
        print(f"\n{'=' * 60}")
        print(f" Model: {model_type.upper()}   Ticker: {args.ticker}")
        print(f"{'=' * 60}")

        # ── Regime detection ──────────────────────────────────────────
        result = run_detection(
            ticker=args.ticker,
            model_type=model_type,
            start_date=args.start_date,
            end_date=args.end_date,
            n_states=args.n_states,
            force_download=args.force_download,
        )

        print(f"\n{result.summary()}")

        # ── Strategy params for current regime ────────────────────────
        params = strategy.get_params(result.current_regime)
        print(f"\nStrategy Parameters for Current Regime ({result.current_regime}):")
        for k, v in params.items():
            if k != "description":
                print(f"  {k:<20}: {v}")
        print(f"  Description         : {params['description']}")

        # ── Strategy summary table ────────────────────────────────────
        print(f"\nFull Strategy Table:")
        print(strategy.regime_summary().to_string())

        # ── Export CSV ────────────────────────────────────────────────
        if args.export:
            export_path = Path(args.export).stem + f"_{model_type}" + ".csv"
            df_out = pd.DataFrame({
                "regime": result.regime_series,
                "state_id": result.raw_state_series,
            })
            df_out.to_csv(export_path)
            print(f"\nRegime series exported to: {export_path}")

        # ── Walk-forward backtest ─────────────────────────────────────
        bt_result = None
        if args.backtest:
            print(f"\nRunning walk-forward backtest …")
            bt_result = run_backtest(
                ticker=args.ticker,
                model_type=model_type,
                start_date=args.start_date,
                end_date=args.end_date,
                n_states=args.n_states,
                force_download=args.force_download,
            )
            print(f"\n{bt_result.summary()}")

        # ── Plotting ──────────────────────────────────────────────────
        if args.plot or args.save_plots:
            try:
                from visualization.plotter import RegimePlotter
                import matplotlib
                if not args.plot:
                    matplotlib.use("Agg")   # headless when only saving

                plotter = RegimePlotter(
                    save_dir=args.save_plots,
                    show=args.plot,
                )
                plotter.plot_dashboard(
                    price_df=result.price_data,
                    regime_series=result.regime_series,
                    feature_df=result.feature_data,
                    model=result.model,
                    equity_curve=bt_result.equity_curve if bt_result else None,
                    benchmark=bt_result.benchmark if bt_result else None,
                    ticker=args.ticker,
                    model_type=model_type,
                )
                plotter.plot_regime_distribution(
                    regime_series=result.regime_series,
                    ticker=args.ticker,
                )
            except ImportError as exc:
                logger.warning("Plotting skipped: %s", exc)

    print("\nDone.")


if __name__ == "__main__":
    main()
