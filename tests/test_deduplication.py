import numpy as np
import pandas as pd

from nids.data.deduplication import row_hashes, verify_hash_collisions
from nids.features.feature_groups import MODEL_FEATURES


def _frame(rows: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=MODEL_FEATURES)


def test_identical_rows_same_label_hash_equal():
    row = [1.0] * len(MODEL_FEATURES)
    df = _frame([row, row])
    codes = np.array([1, 1], dtype=np.int8)
    h = row_hashes(df, codes)
    assert h[0] == h[1]


def test_identical_features_different_label_hash_differs():
    row = [1.0] * len(MODEL_FEATURES)
    df = _frame([row, row])
    codes = np.array([0, 1], dtype=np.int8)
    h = row_hashes(df, codes)
    assert h[0] != h[1]


def test_different_feature_value_changes_hash():
    row_a = [1.0] * len(MODEL_FEATURES)
    row_b = list(row_a)
    row_b[3] = 2.0
    df = _frame([row_a, row_b])
    codes = np.array([0, 0], dtype=np.int8)
    h = row_hashes(df, codes)
    assert h[0] != h[1]


def test_hash_is_deterministic_across_calls():
    row = [float(i) for i in range(len(MODEL_FEATURES))]
    df = _frame([row])
    codes = np.array([2], dtype=np.int8)
    h1 = row_hashes(df, codes)
    h2 = row_hashes(df, codes)
    assert h1[0] == h2[0]


def test_verify_hash_collisions_confirms_true_duplicates():
    df_a = _frame([[1.0] * len(MODEL_FEATURES)])
    df_b = _frame([[1.0] * len(MODEL_FEATURES)])
    eq = verify_hash_collisions(df_a, np.array([0]), df_b, np.array([0]))
    assert eq[0]


def test_verify_hash_collisions_rejects_different_rows():
    df_a = _frame([[1.0] * len(MODEL_FEATURES)])
    row_b = [1.0] * len(MODEL_FEATURES)
    row_b[0] = 99.0
    df_b = _frame([row_b])
    eq = verify_hash_collisions(df_a, np.array([0]), df_b, np.array([0]))
    assert not eq[0]
