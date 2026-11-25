"""Mean +/- sample-standard-deviation aggregation over the 5 seeds (n=5)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def aggregate_over_seeds(df: pd.DataFrame, group_cols: list[str], value_cols: list[str]) -> pd.DataFrame:
    """Aggregate a long-format per-seed metrics table to mean +/- std.

    ``df`` must have one row per (group, seed). The returned table has one
    row per group with ``{col}_mean``, ``{col}_std`` and ``n_seeds``.
    """
    grouped = df.groupby(group_cols, dropna=False)
    out = grouped[value_cols].agg(["mean", "std"])
    out.columns = [f"{c}_{stat}" for c, stat in out.columns]
    out["n_seeds"] = grouped.size().to_numpy()
    out = out.reset_index()
    # Sample std of n=1 is NaN by pandas convention; report 0.0 instead.
    for c in value_cols:
        out[f"{c}_std"] = out[f"{c}_std"].fillna(0.0)
    return out
