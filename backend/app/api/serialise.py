"""JSON-safety for numeric payloads.

The quant layer legitimately produces values that JSON cannot represent:

* ``inf`` — Sortino when a return series has no losing day, and profit factor
  when a strategy has no losing trade. Both are correct answers, not errors.
* ``nan`` — indicator warm-up periods, and undefined ratios.
* ``numpy.float64`` / ``numpy.int64`` — pandas returns these everywhere, and
  ``json.dumps`` refuses them.

Python's ``json`` emits bare ``Infinity`` and ``NaN`` tokens for the first two,
which are **not valid JSON**: ``JSON.parse`` in the browser throws on them. So
every response passes through :func:`clean` on the way out.

``inf`` becomes ``null`` rather than a large sentinel number. A sentinel would be
plotted as a real value and silently distort a chart; ``null`` is skipped by
every charting library and reads honestly as "undefined here".
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def clean(value: Any) -> Any:
    """Recursively convert ``value`` into something ``json.dumps`` accepts.

    Handles dicts, lists, tuples, numpy scalars, pandas NA, datetimes and
    non-finite floats. Anything unrecognised is returned unchanged so genuine
    type errors surface rather than being papered over.
    """
    # Order matters: bool is a subclass of int, and numpy bools are not Python bools.
    if isinstance(value, (bool, np.bool_)):
        return bool(value)

    if value is None or value is pd.NaT:
        return None

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (float, np.floating)):
        as_float = float(value)
        # inf and nan are both "no representable answer"; say so with null.
        return as_float if math.isfinite(as_float) else None

    if isinstance(value, int):
        return value

    if isinstance(value, str):
        return value

    if isinstance(value, (pd.Timestamp,)):
        return str(value.date())

    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set, np.ndarray)):
        return [clean(v) for v in value]

    if isinstance(value, pd.Series):
        return [clean(v) for v in value.tolist()]

    if isinstance(value, pd.DataFrame):
        return frame_to_records(value)

    return value


def frame_to_records(df: pd.DataFrame, index_name: str | None = None) -> list[dict]:
    """DataFrame -> list of JSON-safe row dicts.

    ``index_name`` promotes the index into a column of that name, which is how
    date-indexed series reach the dashboard.
    """
    out = df.reset_index() if index_name else df
    if index_name:
        out = out.rename(columns={out.columns[0]: index_name})
    return [clean(row) for row in out.to_dict(orient="records")]


def series_to_pairs(series: pd.Series, value_name: str = "value") -> list[dict]:
    """Date-indexed Series -> ``[{"date": ..., value_name: ...}]``."""
    return [
        {"date": str(idx.date()) if hasattr(idx, "date") else str(idx), value_name: clean(val)}
        for idx, val in series.items()
    ]
