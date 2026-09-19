"""Phase 1 bootstrap: fetch, validate and cache all assets, then self-check.

Run once with network access:

    .venv/Scripts/python.exe scripts/bootstrap_data.py

The resulting parquet files in ``data_cache/`` are committed to the repo so the
platform (and the demo) works offline.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ASSETS
from app.data.store import load_asset, load_panel, quality_report


def main() -> int:
    refresh = "--refresh" in sys.argv
    failures: list[str] = []

    print("=" * 74)
    print("PHASE 1 — DATA PIPELINE")
    print("=" * 74)

    for key, asset in ASSETS.items():
        try:
            df = load_asset(key, refresh=refresh)
            rep = quality_report(key)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the sweep
            failures.append(f"{key}: {type(exc).__name__}: {exc}")
            print(f"\n[FAIL] {key:5} ({asset.ticker}) -> {exc}")
            continue

        print(f"\n[ OK ] {key:5} ({asset.ticker}, {asset.asset_class}, ann={asset.ann_factor})")
        print(f"       rows {rep['rows_out']:>5}   {rep['start']} -> {rep['end']}")
        print(
            f"       dropped: null_close={rep['dropped_null_close']} "
            f"non_positive={rep['dropped_non_positive']} "
            f"ohlc_repaired={rep['ohlc_repaired']} neg_vol={rep['negative_volume_zeroed']}"
        )
        print(f"       max gap {rep['max_gap_days']}d, gaps>7d: {rep['gaps_over_7d']}")
        print(f"       last close: {df['close'].iloc[-1]:,.2f}")

        # Invariants that must hold after validation.
        if not df.index.is_monotonic_increasing:
            failures.append(f"{key}: index not sorted")
        if df.index.has_duplicates:
            failures.append(f"{key}: duplicate dates")
        if not (df["high"] >= df["low"]).all():
            failures.append(f"{key}: high < low survived validation")
        if not (df[["open", "high", "low", "close"]] > 0).all().all():
            failures.append(f"{key}: non-positive price survived validation")
        if len(df) < 500:
            failures.append(f"{key}: only {len(df)} rows, expected years of history")

    # Cross-asset alignment is the part that silently corrupts correlations.
    print("\n" + "-" * 74)
    try:
        panel = load_panel()
        print(f"ALIGNED PANEL: {panel.shape[0]} common trading days x {panel.shape[1]} assets")
        print(f"       {panel.index.min().date()} -> {panel.index.max().date()}")
        if panel.isna().any().any():
            failures.append("panel: NaNs survived the inner join")
        if panel.shape[0] < 400:
            failures.append(f"panel: only {panel.shape[0]} aligned rows")

        # Show what alignment cost us, per asset.
        for key in ASSETS:
            own = len(load_asset(key))
            print(f"       {key:5} {own:>5} own rows -> {panel.shape[0]} after alignment "
                  f"({panel.shape[0] / own:.0%} retained)")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"panel: {type(exc).__name__}: {exc}")
        print(f"[FAIL] panel -> {exc}")

    print("\n" + "=" * 74)
    if failures:
        print(f"PHASE 1 FAILED — {len(failures)} issue(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PHASE 1 PASSED — all assets cached, validated and aligned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
