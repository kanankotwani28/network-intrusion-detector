"""Row-level validation of numeric model features (proposal Section 7.2).

Every model feature must be numeric, finite and non-negative (all 40 model
features are counts, codes, durations or rates). Rows failing any check are
dropped and counted by reason; nothing is imputed.

Anomalies that are *not* invalid (zero-duration flows, direction durations
longer than the whole flow, values close to a 32-bit millisecond timer wrap)
are flagged and counted but left unchanged: altering them would be an
undocumented data edit.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nids.features.feature_groups import DURATION_FEATURES, INTEGER_FEATURES, MODEL_FEATURES

# 2**32 microseconds expressed in milliseconds: a duration near this value is
# characteristic of a wrapped 32-bit timer (flagged only).
TIMER_WRAP_MS = 4_294_967.296
TIMER_WRAP_MARGIN_MS = 1_000.0

# Priority order: a row's *primary* drop reason is the first one that applies.
DROP_REASONS = ("non_numeric", "nan", "inf", "negative")


@dataclass
class ValidationStats:
    """Streaming accumulator of validation outcomes across chunks."""

    # (reason, column) -> number of failing cells
    cell_failures: Counter = field(default_factory=Counter)
    # (project_class_code, primary_reason) -> number of dropped rows
    row_drops: Counter = field(default_factory=Counter)
    # (project_class_code, flag) -> number of flagged (kept) rows
    flags: Counter = field(default_factory=Counter)
    # column -> number of non-integral values in an integer column (kept)
    non_integral: Counter = field(default_factory=Counter)
    rows_checked: int = 0
    rows_valid: int = 0

    def merge_chunk(self, other: "ValidationStats") -> None:
        self.cell_failures.update(other.cell_failures)
        self.row_drops.update(other.row_drops)
        self.flags.update(other.flags)
        self.non_integral.update(other.non_integral)
        self.rows_checked += other.rows_checked
        self.rows_valid += other.rows_valid

    def to_frame(self, class_names: list[str]) -> pd.DataFrame:
        """Long-format table written to ``validation_drops.csv``."""
        rows: list[dict[str, object]] = []
        for (code, reason), n in sorted(self.row_drops.items()):
            rows.append(
                {"level": "row_dropped", "project_class": class_names[code], "reason": reason, "column": "", "count": n}
            )
        for (reason, col), n in sorted(self.cell_failures.items()):
            rows.append({"level": "cell_failure", "project_class": "all", "reason": reason, "column": col, "count": n})
        for (code, flag), n in sorted(self.flags.items()):
            rows.append(
                {"level": "row_flagged_kept", "project_class": class_names[code], "reason": flag, "column": "", "count": n}
            )
        for col, n in sorted(self.non_integral.items()):
            rows.append(
                {"level": "non_integral_kept", "project_class": "all", "reason": "non_integral", "column": col, "count": n}
            )
        rows.append(
            {"level": "summary", "project_class": "all", "reason": "rows_checked", "column": "", "count": self.rows_checked}
        )
        rows.append(
            {"level": "summary", "project_class": "all", "reason": "rows_valid", "column": "", "count": self.rows_valid}
        )
        return pd.DataFrame(rows, columns=["level", "project_class", "reason", "column", "count"])


def coerce_features(chunk: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """Convert the 40 model features to float64.

    Returns the numeric frame and a boolean matrix marking cells that could
    not be parsed as numbers (before coercion they were non-empty).
    """
    numeric = {}
    non_numeric = np.zeros((len(chunk), len(MODEL_FEATURES)), dtype=bool)
    for j, col in enumerate(MODEL_FEATURES):
        s = chunk[col]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            numeric[col] = s.to_numpy(dtype=np.float64, na_value=np.nan)
        else:
            coerced = pd.to_numeric(s, errors="coerce")
            arr = coerced.to_numpy(dtype=np.float64, na_value=np.nan)
            non_numeric[:, j] = np.isnan(arr) & s.notna().to_numpy()
            numeric[col] = arr
    frame = pd.DataFrame(numeric, index=chunk.index)
    # Canonicalise -0.0 to 0.0 so equal values always hash identically.
    frame = frame + 0.0
    return frame, non_numeric


def validate_chunk(chunk: pd.DataFrame, codes: np.ndarray) -> tuple[pd.DataFrame, np.ndarray, ValidationStats]:
    """Validate one chunk of *eligible* rows (already filtered to 4 classes).

    Parameters
    ----------
    chunk:
        Raw rows containing at least the 40 model feature columns.
    codes:
        Project class code of each row (int8, no ``-1``).

    Returns
    -------
    features:
        float64 frame of the 40 model features for *all* rows of the chunk.
    valid:
        boolean mask of rows that passed every check.
    stats:
        validation statistics for this chunk.
    """
    stats = ValidationStats()
    features, non_numeric = coerce_features(chunk)
    values = features.to_numpy()

    nan_mask = np.isnan(values) & ~non_numeric
    inf_mask = np.isinf(values)
    with np.errstate(invalid="ignore"):
        neg_mask = values < 0

    masks = {"non_numeric": non_numeric, "nan": nan_mask, "inf": inf_mask, "negative": neg_mask}
    invalid_any = np.zeros(len(chunk), dtype=bool)
    primary = np.full(len(chunk), "", dtype=object)
    for reason in DROP_REASONS:
        m = masks[reason]
        col_counts = m.sum(axis=0)
        for j in np.flatnonzero(col_counts):
            stats.cell_failures[(reason, MODEL_FEATURES[j])] += int(col_counts[j])
        row_fail = m.any(axis=1)
        newly = row_fail & ~invalid_any
        primary[newly] = reason
        invalid_any |= row_fail

    for code, reason in zip(codes[invalid_any], primary[invalid_any]):
        stats.row_drops[(int(code), str(reason))] += 1

    valid = ~invalid_any
    stats.rows_checked = len(chunk)
    stats.rows_valid = int(valid.sum())

    # Flags on valid rows only (kept, counted).
    v = features.loc[valid]
    vc = codes[valid]
    flow = v["FLOW_DURATION_MILLISECONDS"].to_numpy()
    d_in = v["DURATION_IN"].to_numpy()
    d_out = v["DURATION_OUT"].to_numpy()
    wrap_lo = TIMER_WRAP_MS - TIMER_WRAP_MARGIN_MS
    flag_defs = {
        "zero_flow_duration": flow == 0,
        "zero_duration_in": d_in == 0,
        "zero_duration_out": d_out == 0,
        "direction_duration_exceeds_flow": (d_in > flow + 1.0) | (d_out > flow + 1.0),
        # Reported per column, not combined: FLOW_DURATION_MILLISECONDS is a
        # known nProbe 32-bit microsecond-counter overflow in this dataset
        # and wraps far more often than DURATION_IN/DURATION_OUT, so an
        # "any of the three" flag would hide that asymmetry.
        "near_32bit_timer_wrap_flow_duration": flow >= wrap_lo,
        "near_32bit_timer_wrap_duration_in": d_in >= wrap_lo,
        "near_32bit_timer_wrap_duration_out": d_out >= wrap_lo,
    }
    for name, m in flag_defs.items():
        for code, n in zip(*np.unique(vc[m], return_counts=True)):
            stats.flags[(int(code), name)] += int(n)

    ints = v[INTEGER_FEATURES].to_numpy()
    frac = (ints != np.floor(ints)).sum(axis=0)
    for j in np.flatnonzero(frac):
        stats.non_integral[INTEGER_FEATURES[j]] += int(frac[j])

    return features, valid, stats
