"""Header verification against the canonical schema (proposal Appendix A).

Column *names* must match exactly (no renaming or substitution). Column
*order* differences are reported but are not fatal, because every module
selects columns by name. Missing required columns are fatal. Unexpected
extra columns are reported so they can be reviewed (e.g. an inter-arrival
time column would have to be added to the timing group).
"""

from __future__ import annotations

import pandas as pd

from nids.features.feature_groups import (
    FLOAT_FEATURES,
    IDENTIFIER_FEATURES,
    PUBLISHED_COLUMNS,
    TARGET_COLUMNS,
)


class SchemaError(ValueError):
    """Raised when required columns are missing from the dataset header."""


def expected_kind(column: str) -> str:
    if column in ("IPV4_SRC_ADDR", "IPV4_DST_ADDR"):
        return "string"
    if column == "Attack":
        return "string"
    if column == "Label":
        return "integer"
    if column in FLOAT_FEATURES:
        return "float"
    return "integer"


def verify_header(columns: list[str], first_chunk: pd.DataFrame | None = None) -> pd.DataFrame:
    """Compare a file header with Appendix A.

    Returns a long-format table with one row per check (``check``,
    ``target``, ``expected``, ``observed``, ``passed``). Raises
    :class:`SchemaError` if any required column is missing.
    """
    rows: list[dict[str, object]] = []
    found_pos = {c: i for i, c in enumerate(columns)}

    for i, col in enumerate(PUBLISHED_COLUMNS):
        present = col in found_pos
        rows.append(
            {
                "check": "column_present",
                "target": col,
                "expected": "present",
                "observed": "present" if present else "MISSING",
                "passed": present,
            }
        )
        if present:
            rows.append(
                {
                    "check": "column_position",
                    "target": col,
                    "expected": i,
                    "observed": found_pos[col],
                    "passed": found_pos[col] == i,
                }
            )
        if present and first_chunk is not None:
            dtype = str(first_chunk[col].dtype)
            kind = expected_kind(col)
            if kind == "string":
                ok = not pd.api.types.is_numeric_dtype(first_chunk[col]) or col == "Label"
            elif kind == "integer":
                ok = pd.api.types.is_integer_dtype(first_chunk[col])
            else:
                ok = pd.api.types.is_numeric_dtype(first_chunk[col])
            rows.append(
                {
                    "check": "dtype_first_chunk",
                    "target": col,
                    "expected": kind,
                    "observed": dtype,
                    # Integers parsed as float (e.g. due to blanks) are reported,
                    # not fatal: values are validated row by row later.
                    "passed": bool(ok),
                }
            )

    extras = [c for c in columns if c not in PUBLISHED_COLUMNS]
    for col in extras:
        rows.append(
            {
                "check": "unexpected_column",
                "target": col,
                "expected": "absent",
                "observed": "present",
                "passed": False,
            }
        )
    rows.append(
        {
            "check": "column_count",
            "target": "all",
            "expected": len(PUBLISHED_COLUMNS),
            "observed": len(columns),
            "passed": len(columns) == len(PUBLISHED_COLUMNS),
        }
    )

    report = pd.DataFrame(rows)
    missing = [c for c in PUBLISHED_COLUMNS if c not in found_pos]
    required_missing = [c for c in missing if c not in IDENTIFIER_FEATURES or c in TARGET_COLUMNS]
    if required_missing:
        raise SchemaError(f"Dataset header is missing required columns: {required_missing}")
    return report
