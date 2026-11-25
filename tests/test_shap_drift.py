import numpy as np
import pandas as pd

from nids.data.label_mapping import BENIGN_CODE
from nids.explainability.shap_drift import audit_attribution_drift, build_audit_sample, group_summary
from nids.features.feature_groups import MODEL_FEATURES
from nids.models.base import fit_model

BASE_PARAMS = {
    "n_estimators": 40, "learning_rate": 0.2, "num_leaves": 15, "subsample": 0.8,
    "subsample_freq": 1, "colsample_bytree": 0.8, "class_weight": "balanced", "n_jobs": 1, "verbose": -1,
}


def _toy_df(n_per_class=100, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    for code in range(4):
        data = {f: np.abs(rng.normal(loc=code, scale=1.0, size=n_per_class)) for f in MODEL_FEATURES}
        df = pd.DataFrame(data)
        df["y"] = code
        frames.append(df)
    return pd.concat(frames, ignore_index=True).sample(frac=1.0, random_state=seed).reset_index(drop=True)


def test_build_audit_sample_never_uses_predicted_class():
    y_true = np.array([1, 1, 2, 2, BENIGN_CODE])
    y_pred_clean = np.array([1, 1, 2, 2, BENIGN_CODE])  # all correctly detected clean
    y_pred_ood = np.array([BENIGN_CODE, 1, BENIGN_CODE, 2, BENIGN_CODE])  # flows 0,2 evade
    sample = build_audit_sample(y_true, y_pred_clean, y_pred_ood, cap_per_class=300, min_evaded=1, seed=1)
    # Only evaded flows (0, 2) should be selected for classes with >= min_evaded evasions.
    assert set(sample.indices.tolist()) <= {0, 2}


def test_build_audit_sample_substitution_flagged_when_too_few_evaded():
    y_true = np.array([1] * 10)
    y_pred_clean = np.array([1] * 10)
    y_pred_ood = np.array([1] * 10)  # zero evaded
    sample = build_audit_sample(y_true, y_pred_clean, y_pred_ood, cap_per_class=5, min_evaded=30, seed=1)
    assert "DDoS" in sample.substituted_classes
    assert len(sample.indices) == 5


def test_audit_attribution_drift_uses_ground_truth_class():
    df = _toy_df()
    model = fit_model("m1", MODEL_FEATURES, df, BASE_PARAMS, seed=42)
    y_true = df["y"].to_numpy()
    y_pred = model.predict(df)
    sample = build_audit_sample(y_true, y_pred, y_pred, cap_per_class=10, min_evaded=1, seed=1)
    drift = audit_attribution_drift(model, df, df, sample)  # clean==perturbed -> shift ~ 0
    assert np.allclose(drift["mean_signed_shift"], 0.0, atol=1e-6)
    assert set(drift["group"]) <= {"fragile_timing_rate", "other_structural", "engineered_invariant"}


def test_group_summary_aggregates_per_model():
    df = _toy_df()
    model = fit_model("m1", MODEL_FEATURES, df, BASE_PARAMS, seed=42)
    y_true = df["y"].to_numpy()
    y_pred = model.predict(df)
    sample = build_audit_sample(y_true, y_pred, y_pred, cap_per_class=10, min_evaded=1, seed=1)
    drift = audit_attribution_drift(model, df, df, sample)
    summary = group_summary({"m1": drift})
    assert set(summary["model"]) == {"m1"}
    assert np.isclose(summary["attribution_share_clean"].sum(), 1.0, atol=1e-6)
