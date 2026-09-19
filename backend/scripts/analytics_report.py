"""Phase 2 verification: run the analytics engine over real data and print it.

    .venv/Scripts/python.exe scripts/analytics_report.py

Tests prove the maths is right in isolation. This proves the numbers are
*plausible* on real assets — the check no unit test can make for you.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analytics.correlation import correlation_matrix, rolling_correlation_all, sample_size
from app.analytics.indicators import compute_indicators
from app.analytics.metrics import daily_returns, summarise
from app.analytics.regime import classify, regime_breakdown
from app.config import ASSETS
from app.data.store import load_asset


def pct(x: float) -> str:
    return f"{x * 100:>8.2f}%"


def num(x: float) -> str:
    if x == float("inf"):
        return "     inf"
    return f"{x:>8.2f}"


def main() -> int:
    warnings: list[str] = []

    print("=" * 78)
    print("PHASE 2 - ANALYTICS ENGINE")
    print("=" * 78)

    # ---------------------------------------------------------- metrics
    print("\nBUY-AND-HOLD RISK / RETURN (full history, per-asset annualisation)\n")
    hdr = f"{'ASSET':6}{'ANN':>5}{'TOTAL':>10}{'CAGR':>10}{'VOL':>10}{'SHARPE':>9}{'SORTINO':>9}{'CALMAR':>9}{'MAXDD':>10}{'DDdays':>8}"
    print(hdr)
    print("-" * len(hdr))

    for key, asset in ASSETS.items():
        rets = daily_returns(load_asset(key)["close"])
        s = summarise(rets, asset.ann_factor)
        print(
            f"{key:6}{asset.ann_factor:>5}{pct(s['total_return']):>10}{pct(s['cagr']):>10}"
            f"{pct(s['volatility']):>10}{num(s['sharpe'])}{num(s['sortino'])}"
            f"{num(s['calmar'])}{pct(s['max_drawdown']):>10}{s['max_drawdown_duration']:>8}"
        )

        if not -1.0 < s["max_drawdown"] <= 0.0:
            warnings.append(f"{key}: max drawdown {s['max_drawdown']:.4f} outside (-1, 0]")
        if not -5 < s["sharpe"] < 5:
            warnings.append(f"{key}: implausible Sharpe {s['sharpe']:.2f}")
        if not 0 < s["volatility"] < 3:
            warnings.append(f"{key}: implausible volatility {s['volatility']:.2f}")

    # ---------------------------------------------------------- indicators
    print("\n\nINDICATOR COVERAGE (non-null share after warm-up)\n")
    for key in ASSETS:
        ind = compute_indicators(load_asset(key))
        cols = ["sma_20", "sma_200", "ema_12", "rsi", "macd", "bb_z", "atr", "roc"]
        parts = []
        for c in cols:
            share = ind[c].notna().mean()
            parts.append(f"{c}={share:.0%}")
            if share < 0.85:
                warnings.append(f"{key}: {c} only {share:.0%} populated")
        print(f"  {key:6} {'  '.join(parts)}")
        rsi_v = ind["rsi"].dropna()
        if not (rsi_v.between(0, 100).all()):
            warnings.append(f"{key}: RSI out of bounds")

    # ---------------------------------------------------------- correlation
    print("\n\nCORRELATION MATRIX (daily returns, common calendar)\n")
    cm = correlation_matrix()
    print(f"  n = {sample_size()} observations\n")
    print("        " + "".join(f"{c:>9}" for c in cm.columns))
    for r in cm.index:
        print(f"  {r:6}" + "".join(f"{cm.loc[r, c]:>9.4f}" for c in cm.columns))

    print("\n  ROLLING 90d CORRELATION - range over the full history\n")
    rc = rolling_correlation_all(90)
    for col in rc.columns:
        s = rc[col].dropna()
        print(f"  {col:12} min={s.min():+.3f}  max={s.max():+.3f}  last={s.iloc[-1]:+.3f}  swing={s.max() - s.min():.3f}")
        if s.max() - s.min() < 0.05:
            warnings.append(f"{col}: rolling correlation barely moves - suspicious")

    # ---------------------------------------------------------- regime
    print("\n\nREGIME ATTRIBUTION\n")
    for key in ASSETS:
        reg = classify(key)
        labelled = reg["trend_regime"].notna().sum()
        print(f"  {key} - {labelled} labelled bars of {len(reg)}")
        for row in regime_breakdown(key):
            print(
                f"      {row['axis']:11}{row['regime']:12}{row['days']:>6}d "
                f"({row['share_of_period']:>5.1%})  CAGR{pct(row['cagr'])}  "
                f"vol{pct(row['volatility'])}  sharpe{num(row['sharpe'])}"
            )
        print()

    # ---------------------------------------------------------- cross-checks
    print("=" * 78)
    for key in ASSETS:
        rows = {r["regime"]: r for r in regime_breakdown(key) if r["axis"] == "volatility"}
        if "high_vol" in rows and "low_vol" in rows:
            if rows["high_vol"]["volatility"] <= rows["low_vol"]["volatility"]:
                warnings.append(f"{key}: high_vol regime is not more volatile than low_vol")

    if warnings:
        print(f"PHASE 2 - {len(warnings)} PLAUSIBILITY WARNING(S):")
        for w in warnings:
            print(f"  ! {w}")
        return 1
    print("PHASE 2 PASSED - all values within plausible ranges.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
