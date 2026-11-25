"""Deterministic row hashing and exact-duplicate detection (Section 7.3).

Duplicate key = hash(40 model feature columns + project label). Hashing is
vectorised with :func:`pandas.util.hash_pandas_object` (a 64-bit hash,
deterministic for a given ``hash_key``) applied to a canonical
representation of each row: the float64 feature vector is first viewed as
raw bytes (with ``-0.0`` already normalised to ``0.0`` in
:func:`nids.data.validation.coerce_features`) and the label is appended, so
two rows hash identically iff their feature values and project label are
bit-identical.

This is ~1e5-1e6x faster than hashing row-by-row in a Python loop, which
matters because Pass 1 hashes every valid row of an 18.9M-row file.

A 64-bit hash can in principle collide across unrelated rows. With on the
order of a few million eligible rows the expected number of collisions is
far below 1 (birthday bound ~ n^2 / 2^65), so this is treated as negligible
and documented as a limitation rather than guarded with a full row-equality
pass (which would require holding every raw feature row in memory across
the whole scan, defeating the memory-safety requirement of Section 7.1).
:func:`verify_hash_collisions` is provided for callers that *do* hold both
row sets in memory (e.g. a unit test, or Pass 2 output) and want to confirm
a specific suspected collision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nids.features.feature_groups import MODEL_FEATURES

_HASH_KEY = "0123456789123456"  # fixed key -> deterministic across runs


def row_hashes(features: pd.DataFrame, project_class_code: np.ndarray) -> np.ndarray:
    """Vectorised 64-bit hash of each row's (feature vector, label).

    ``features`` must already be the coerced float64 frame in
    :data:`MODEL_FEATURES` order (see :func:`nids.data.validation.coerce_features`).
    """
    arr = np.ascontiguousarray(features[MODEL_FEATURES].to_numpy(dtype="<f8", copy=False))
    # One opaque bytes object per row -> hash_pandas_object hashes it as a
    # single "object" column, combining all feature values in one pass.
    row_bytes = pd.Series(list(arr.view(f"S{arr.shape[1] * 8}").reshape(-1)), copy=False)
    labels = pd.Series(np.asarray(project_class_code, dtype=np.int8))
    combined = pd.DataFrame({"features": row_bytes.to_numpy(), "label": labels.to_numpy()})
    hashed = pd.util.hash_pandas_object(combined, index=False, hash_key=_HASH_KEY, categorize=False)
    return hashed.to_numpy(dtype=np.uint64)


def verify_hash_collisions(
    features_a: pd.DataFrame, label_a: np.ndarray, features_b: pd.DataFrame, label_b: np.ndarray
) -> np.ndarray:
    """Exact equality check for two row sets suspected to share a hash value.

    Returns a boolean array: True where row ``i`` of A truly equals row
    ``i`` of B (feature values and label), guarding against a 64-bit hash
    collision being mistaken for a duplicate.
    """
    feat_eq = np.all(
        features_a[MODEL_FEATURES].to_numpy(dtype=np.float64)
        == features_b[MODEL_FEATURES].to_numpy(dtype=np.float64),
        axis=1,
    )
    return feat_eq & (np.asarray(label_a) == np.asarray(label_b))
