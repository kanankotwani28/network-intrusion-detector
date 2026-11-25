import numpy as np
import pandas as pd

from nids.features.feature_groups import ENGINEERED_FEATURES, MODEL_FEATURES, STRUCTURAL_FEATURES, TIMING_FEATURES
from nids.models.base import fit_model
from nids.models.shap_selection import class_capped_subset, select_m5_features

BASE_PARAMS = {
    "n_estimators": 40,
    "learning_rate": 0.2,
    "num_leaves": 15,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "class_weight": "balanced",
    "n_jobs": 1,
    "verbose": -1,
}


def _toy_df(n_per_class=80, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    for code in range(4):
        data = {f: np.abs(rng.normal(loc=0.0, scale=1.0, size=n_per_class)) for f in MODEL_FEATURES}
        # Make duration strongly predictive of class -> should be flagged fragile.
        data["FLOW_DURATION_MILLISECONDS"] = np.abs(rng.normal(loc=code * 50, scale=1.0, size=n_per_class))
        df = pd.DataFrame(data)
        df["y"] = code
        frames.append(df)
    return pd.concat(frames, ignore_index=True).sample(frac=1.0, random_state=seed).reset_index(drop=True)


def test_class_capped_subset_respects_cap():
    df = _toy_df(n_per_class=100)
    subset = class_capped_subset(df, "y", cap_per_class=30, seed=42)
    counts = subset["y"].value_counts()
    assert (counts <= 30).all()


def test_m5_feature_list_excludes_fragile_timing_and_adds_ratios():
    df = _toy_df()
    m1 = fit_model("m1", MODEL_FEATURES, df, BASE_PARAMS, seed=42)
    result = select_m5_features(
        m1, df, "y", threshold=0.025, sensitivity_thresholds=[0.01, 0.05], cap_per_class=50, seed=42
    )
    assert "FLOW_DURATION_MILLISECONDS" in result.flagged_fragile
    assert "FLOW_DURATION_MILLISECONDS" not in result.feature_list
    assert set(STRUCTURAL_FEATURES).issubset(result.feature_list)
    assert set(ENGINEERED_FEATURES).issubset(result.feature_list)
    assert set(result.retained_timing) == set(TIMING_FEATURES) - set(result.flagged_fragile)
    assert len(result.sensitivity) == 2


def test_importance_shares_sum_to_one():
    df = _toy_df()
    m1 = fit_model("m1", MODEL_FEATURES, df, BASE_PARAMS, seed=42)
    result = select_m5_features(
        m1, df, "y", threshold=0.025, sensitivity_thresholds=[0.01], cap_per_class=50, seed=42
    )
    assert np.isclose(result.importance_table["importance_share"].sum(), 1.0, atol=1e-6)
