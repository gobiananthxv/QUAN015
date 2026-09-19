"""
run_all.py — Single-command runner for the complete ML Market Regime Detection system.

Runs every module in sequence:
  1. Downloads / loads market data
  2. Runs HMM regime detection
  3. Runs GMM regime detection
  4. Walk-forward backtest (HMM + GMM)
  5. Adaptive strategy parameters for current regime
  6. Exports all results to CSV
  7. Saves all plots to ./output/

Usage
-----
    python run_all.py                              # default: SPY, 2010-01-01
    python run_all.py --ticker QQQ
    python run_all.py --ticker AAPL --start 2015-01-01
    python run_all.py --ticker SPY --n-states 3
    python run_all.py --ticker SPY --show-plots    # open interactive windows too
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import warnings
from pathlib import Path

# ── make sibling packages importable ─────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

# ── configure logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_all")

# ── colour helpers ─────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def banner(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 60}{RESET}")

def ok(text: str) -> None:
    print(f"  {GREEN}✔  {text}{RESET}")

def info(text: str) -> None:
    print(f"  {YELLOW}→  {text}{RESET}")


# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the complete ML Market Regime Detection pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--ticker",      default="SPY",        help="Ticker symbol (default: SPY)")
    p.add_argument("--start",       default="2010-01-01", help="Start date YYYY-MM-DD (default: 2010-01-01)")
    p.add_argument("--end",         default=None,         help="End date YYYY-MM-DD (default: today)")
    p.add_argument("--n-states",    default=None, type=int, dest="n_states",
                   help="Fix number of hidden states (default: auto-select via BIC)")
    p.add_argument("--show-plots",  action="store_true", dest="show_plots",
                   help="Also open interactive plot windows (in addition to saving)")
    p.add_argument("--output-dir",  default="output",    dest="output_dir",
                   help="Directory for all exported files (default: ./output/)")
    p.add_argument("--force-download", action="store_true", dest="force_download",
                   help="Re-download data ignoring local cache")
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    t_start = time.perf_counter()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    plots_dir = out / "plots"
    plots_dir.mkdir(exist_ok=True)

    ticker   = args.ticker.upper()
    start    = args.start
    end      = args.end
    n_states = args.n_states

    print(f"\n{BOLD}{'=' * 60}")
    print(f"  ML Market Regime Detection — Full Pipeline")
    print(f"  Ticker: {ticker}   Range: {start} → {end or 'today'}")
    if n_states:
        print(f"  Fixed states: {n_states}")
    print(f"{'=' * 60}{RESET}")

    # ── imports (deferred so errors surface cleanly) ──────────────────────────
    from data.data_loader          import DataLoader
    from features.feature_engineering import FeatureEngineer
    from models.hmm_model          import HMMRegimeModel
    from models.gmm_model          import GMMRegimeModel
    from regime.detector           import RegimeDetector
    from regime.labeler            import RegimeLabeler
    from strategy.adaptive_strategy import AdaptiveStrategy
    from backtest.walk_forward     import WalkForwardBacktest
    from visualization.plotter     import RegimePlotter
    import matplotlib
    if not args.show_plots:
        matplotlib.use("Agg")   # headless — save only, no display

    # =========================================================================
    # STEP 1: Data
    # =========================================================================
    banner("STEP 1 / 7 — Data Download & Caching")
    loader = DataLoader()
    price_df = loader.load(ticker, start=start, end=end, force_download=args.force_download)
    ok(f"Loaded {len(price_df):,} rows  ({price_df.index[0].date()} → {price_df.index[-1].date()})")
    ok(f"Columns: {list(price_df.columns)}")

    # =========================================================================
    # STEP 2: Feature Engineering
    # =========================================================================
    banner("STEP 2 / 7 — Feature Engineering")
    fe = FeatureEngineer()
    X_scaled, valid_idx = fe.fit_transform(price_df)
    raw_features = fe.get_raw_features(price_df)
    ok(f"Feature matrix: {X_scaled.shape[0]} rows × {X_scaled.shape[1]} features")
    ok(f"Features: {FeatureEngineer.FEATURE_NAMES}")

    # Export raw features
    feat_csv = out / f"{ticker}_features.csv"
    raw_features.to_csv(feat_csv)
    ok(f"Raw features exported → {feat_csv}")

    # =========================================================================
    # STEP 3: HMM Regime Detection
    # =========================================================================
    banner("STEP 3 / 7 — HMM Regime Detection")
    info("Fitting HMM (auto-select n_states via BIC) …")
    hmm_detector = RegimeDetector(ticker=ticker, model_type="hmm", n_components=n_states)
    hmm_result   = hmm_detector.run(start=start, end=end, force_download=False)

    print(f"\n{hmm_result.summary()}")
    ok(f"HMM transition matrix:\n")
    _print_matrix(hmm_result.model.transition_matrix, label="Transition P")
    ok(f"Cluster → Regime map: {hmm_result.label_map}")

    # Export HMM regimes
    hmm_csv = out / f"{ticker}_hmm_regimes.csv"
    hmm_result.regime_series.to_frame("regime").join(
        hmm_result.raw_state_series.rename("state_id")
    ).join(
        hmm_result.state_proba
    ).to_csv(hmm_csv)
    ok(f"HMM regimes exported → {hmm_csv}")

    # =========================================================================
    # STEP 4: GMM Regime Detection
    # =========================================================================
    banner("STEP 4 / 7 — GMM Regime Detection")
    info("Fitting GMM (auto-select n_components via BIC) …")
    gmm_detector = RegimeDetector(ticker=ticker, model_type="gmm", n_components=n_states)
    gmm_result   = gmm_detector.run(start=start, end=end, force_download=False)

    print(f"\n{gmm_result.summary()}")
    ok(f"GMM component weights: {gmm_result.model.weights.round(3).tolist()}")
    ok(f"Cluster → Regime map: {gmm_result.label_map}")

    # Export GMM regimes
    gmm_csv = out / f"{ticker}_gmm_regimes.csv"
    gmm_result.regime_series.to_frame("regime").join(
        gmm_result.raw_state_series.rename("state_id")
    ).join(
        gmm_result.state_proba
    ).to_csv(gmm_csv)
    ok(f"GMM regimes exported → {gmm_csv}")

    # =========================================================================
    # STEP 5: Adaptive Strategy Parameters
    # =========================================================================
    banner("STEP 5 / 7 — Adaptive Strategy Parameters")
    strategy = AdaptiveStrategy()

    for model_type, result in [("HMM", hmm_result), ("GMM", gmm_result)]:
        regime = result.current_regime
        params = strategy.get_params(regime)
        print(f"\n  {BOLD}[{model_type}] Current regime: {regime}{RESET}")
        for k, v in params.items():
            if k != "description":
                print(f"    {k:<22}: {v}")
        print(f"    {'description':<22}: {params['description']}")

    print(f"\n{BOLD}  Full Strategy Table:{RESET}")
    print(strategy.regime_summary().to_string())

    # Export strategy table
    strat_csv = out / "strategy_params.csv"
    strategy.regime_summary().to_csv(strat_csv)
    ok(f"\n  Strategy table exported → {strat_csv}")

    # =========================================================================
    # STEP 6: Walk-Forward Backtest
    # =========================================================================
    banner("STEP 6 / 7 — Walk-Forward Backtest (HMM + GMM)")

    bt_results = {}
    for model_type in ["hmm", "gmm"]:
        info(f"Running {model_type.upper()} walk-forward backtest …")
        bt = WalkForwardBacktest(
            ticker=ticker,
            model_type=model_type,
            n_components=n_states,
        )
        bt_result = bt.run(start=start, end=end, force_download=False)
        bt_results[model_type] = bt_result
        print(f"\n{bt_result.summary()}")

        # Export equity curves
        eq_csv = out / f"{ticker}_{model_type}_equity.csv"
        import pandas as pd
        pd.DataFrame({
            "strategy": bt_result.equity_curve,
            "buy_and_hold": bt_result.benchmark,
        }).to_csv(eq_csv)
        ok(f"  Equity curve exported → {eq_csv}")

        # Export fold-level results
        fold_csv = out / f"{ticker}_{model_type}_folds.csv"
        fold_rows = [
            {
                "fold": f.fold_idx,
                "train_start": f.train_start.date(),
                "train_end":   f.train_end.date(),
                "test_start":  f.test_start.date(),
                "test_end":    f.test_end.date(),
                "n_states":    f.n_states,
                "regime_return_%": round(f.regime_return * 100, 3),
                "bh_return_%":     round(f.bh_return * 100, 3),
                "outperformance_%": round(f.outperformance * 100, 3),
                "regimes_detected": "|".join(f.regimes_detected),
            }
            for f in bt_result.fold_results
        ]
        pd.DataFrame(fold_rows).to_csv(fold_csv, index=False)
        ok(f"  Fold results exported → {fold_csv}")

    # =========================================================================
    # STEP 7: Visualizations
    # =========================================================================
    banner("STEP 7 / 7 — Generating Visualizations")
    plotter = RegimePlotter(save_dir=str(plots_dir), show=args.show_plots)

    for model_type, result, label in [
        ("hmm", hmm_result, "HMM"),
        ("gmm", gmm_result, "GMM"),
    ]:
        info(f"Rendering {label} dashboard …")
        bt_res = bt_results[model_type]
        plotter.plot_dashboard(
            price_df    = result.price_data,
            regime_series = result.regime_series,
            feature_df  = result.feature_data,
            model       = result.model,
            equity_curve = bt_res.equity_curve,
            benchmark   = bt_res.benchmark,
            ticker      = ticker,
            model_type  = model_type,
        )
        ok(f"  {label} dashboard saved → {plots_dir}/{ticker}_{model_type}_dashboard.png")

        info(f"Rendering {label} regime distribution …")
        plotter.plot_regime_distribution(result.regime_series, ticker=ticker)
        ok(f"  {label} distribution saved → {plots_dir}/{ticker}_regime_distribution.png")

    # =========================================================================
    # Summary
    # =========================================================================
    elapsed = time.perf_counter() - t_start
    banner(f"ALL DONE  ({elapsed:.1f}s)")

    print(f"\n  {BOLD}Output files in: {out.resolve()}/{RESET}\n")
    for f in sorted(out.rglob("*")):
        if f.is_file():
            size_kb = f.stat().st_size / 1024
            print(f"    {str(f.relative_to(out)):<50}  {size_kb:6.1f} KB")

    print(f"\n  {BOLD}Quick API recap:{RESET}")
    print(f"    HMM current regime  : {BOLD}{hmm_result.current_regime}{RESET}")
    print(f"    GMM current regime  : {BOLD}{gmm_result.current_regime}{RESET}")
    print(f"    HMM n_states chosen : {hmm_result.n_states}")
    print(f"    GMM n_states chosen : {gmm_result.n_states}")

    hmm_m = bt_results["hmm"].metrics
    gmm_m = bt_results["gmm"].metrics
    print(f"\n  {BOLD}Backtest metrics (out-of-sample):{RESET}")
    print(f"  {'Model':<8} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} {'vs B&H CAGR':>12}")
    print(f"  {'─'*50}")
    for label, m in [("HMM", hmm_m), ("GMM", gmm_m)]:
        s, b = m["strategy"], m["benchmark"]
        print(
            f"  {label:<8} {s['cagr']:>7.2%} {s['sharpe']:>8.2f} "
            f"{s['max_drawdown']:>7.2%}  (B&H: {b['cagr']:>6.2%})"
        )
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _print_matrix(matrix, label: str = "") -> None:
    """Pretty-print a 2D numpy array."""
    if label:
        print(f"    {label}:")
    for row in matrix:
        print("    " + "  ".join(f"{v:.3f}" for v in row))


if __name__ == "__main__":
    main()
