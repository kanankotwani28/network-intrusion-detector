"""Target / identifier leakage guards."""

import numpy as np
import pandas as pd
import pytest

from nids.data.ingestion import finalize_sample
from nids.features.feature_groups import (
    ATTACK_COLUMN,
    IDENTIFIER_FEATURES,
    LABEL_COLUMN,
    MODEL_FEATURES,
    TARGET_COLUMNS,
    assert_no_target_columns,
)


def test_assert_no_target_columns_passes_for_clean_feature_list():
    assert_no_target_columns(MODEL_FEATURES)


def test_assert_no_target_columns_rejects_label():
    with pytest.raises(ValueError):
        assert_no_target_columns(MODEL_FEATURES + [LABEL_COLUMN])


def test_assert_no_target_columns_rejects_attack():
    with pytest.raises(ValueError):
        assert_no_target_columns(MODEL_FEATURES + [ATTACK_COLUMN])


def test_assert_no_target_columns_rejects_identifiers():
    for ident in IDENTIFIER_FEATURES:
        with pytest.raises(ValueError):
            assert_no_target_columns(MODEL_FEATURES + [ident])


def test_finalize_sample_never_contains_identifier_or_target_columns(synthetic_df):
    out = finalize_sample(synthetic_df.head(20))
    forbidden = set(IDENTIFIER_FEATURES) | set(TARGET_COLUMNS)
    assert forbidden.isdisjoint(out.columns)
    assert set(MODEL_FEATURES).issubset(out.columns)
