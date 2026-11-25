import numpy as np
import pandas as pd

from nids.data.validation import coerce_features, validate_chunk
from nids.features.feature_groups import MODEL_FEATURES


def _minimal_valid_frame(n: int) -> pd.DataFrame:
    data = {col: np.full(n, 1.0) for col in MODEL_FEATURES}
    return pd.DataFrame(data)


def test_all_finite_non_negative_rows_pass():
    df = _minimal_valid_frame(5)
    codes = np.zeros(5, dtype=np.int8)
    _, valid, stats = validate_chunk(df, codes)
    assert valid.all()
    assert stats.rows_valid == 5


def test_nan_row_is_dropped_and_counted():
    df = _minimal_valid_frame(3)
    df.loc[1, "IN_BYTES"] = np.nan
    codes = np.zeros(3, dtype=np.int8)
    _, valid, stats = validate_chunk(df, codes)
    assert not valid[1]
    assert valid[0] and valid[2]
    assert stats.row_drops[(0, "nan")] == 1


def test_inf_row_is_dropped():
    df = _minimal_valid_frame(3)
    df.loc[0, "OUT_BYTES"] = np.inf
    codes = np.zeros(3, dtype=np.int8)
    _, valid, stats = validate_chunk(df, codes)
    assert not valid[0]
    assert stats.row_drops[(0, "inf")] == 1


def test_negative_row_is_dropped():
    df = _minimal_valid_frame(3)
    df.loc[2, "FLOW_DURATION_MILLISECONDS"] = -5
    codes = np.zeros(3, dtype=np.int8)
    _, valid, stats = validate_chunk(df, codes)
    assert not valid[2]
    assert stats.row_drops[(0, "negative")] == 1


def test_non_numeric_value_is_dropped_and_counted_separately():
    df = _minimal_valid_frame(2).astype(object)
    df.loc[0, "IN_PKTS"] = "garbage"
    codes = np.zeros(2, dtype=np.int8)
    _, valid, stats = validate_chunk(df, codes)
    assert not valid[0]
    assert valid[1]
    assert stats.cell_failures[("non_numeric", "IN_PKTS")] == 1


def test_zero_duration_flows_are_flagged_not_dropped():
    df = _minimal_valid_frame(2)
    df.loc[0, "FLOW_DURATION_MILLISECONDS"] = 0
    codes = np.zeros(2, dtype=np.int8)
    _, valid, stats = validate_chunk(df, codes)
    assert valid.all()
    assert stats.flags[(0, "zero_flow_duration")] == 1


def test_negative_zero_is_canonicalised_to_zero():
    df = _minimal_valid_frame(1)
    df.loc[0, "IN_BYTES"] = -0.0
    features, _ = coerce_features(df)
    assert np.signbit(features["IN_BYTES"].to_numpy()[0]) == False  # noqa: E712
