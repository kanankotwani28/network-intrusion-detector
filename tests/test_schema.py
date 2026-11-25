import pandas as pd
import pytest

from nids.data.schema import SchemaError, verify_header
from nids.features.feature_groups import (
    IDENTIFIER_FEATURES,
    MODEL_FEATURES,
    PUBLISHED_COLUMNS,
)


def test_full_header_passes_and_counts_43_features():
    report = verify_header(PUBLISHED_COLUMNS)
    assert report[report["check"] == "column_count"]["passed"].all()
    assert len(MODEL_FEATURES) == 40
    assert len(IDENTIFIER_FEATURES) == 3


def test_missing_required_column_raises():
    cols = [c for c in PUBLISHED_COLUMNS if c != "IN_BYTES"]
    with pytest.raises(SchemaError):
        verify_header(cols)


def test_missing_identifier_is_not_fatal():
    # Identifiers are dropped anyway; a file without IPV4_SRC_ADDR should not
    # crash header verification outright (but is reported).
    cols = [c for c in PUBLISHED_COLUMNS if c != "IPV4_SRC_ADDR"]
    report = verify_header(cols)
    row = report[(report["check"] == "column_present") & (report["target"] == "IPV4_SRC_ADDR")]
    assert not row["passed"].iloc[0]


def test_unexpected_extra_column_is_reported():
    cols = list(PUBLISHED_COLUMNS) + ["SOME_NEW_FEATURE"]
    report = verify_header(cols)
    extra = report[report["check"] == "unexpected_column"]
    assert "SOME_NEW_FEATURE" in set(extra["target"])


def test_reordered_header_flagged_but_not_fatal():
    cols = list(PUBLISHED_COLUMNS)
    cols[0], cols[1] = cols[1], cols[0]
    report = verify_header(cols)  # must not raise
    pos_check = report[(report["check"] == "column_position") & (~report["passed"])]
    assert len(pos_check) >= 2
