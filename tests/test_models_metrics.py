import numpy as np
import pandas as pd
import pytest

from nids.data.label_mapping import BENIGN_CODE
from nids.evaluation.metrics import (
    binary_attack_detection_recall,
    clean_classification_report,
    clean_false_positive_rate,
    confusion_matrix_table,
)
from nids.features.feature_groups import MODEL_FEATURES, STRUCTURAL_FEATURES
from nids.models.base import build_estimator, feature_importance_table, fit_model


def _toy_df(n_per_class=60, seed=0):
    rng = np.random.default_rng(seed)
    frames = []
    for code in range(4):
        data = {f: rng.normal(loc=code, scale=1.0, size=n_per_class) + 10 for f in MODEL_FEATURES}
        data = {f: np.abs(v) for f, v in data.items()}
        df = pd.DataFrame(data)
        df["y"] = code
        frames.append(df)
    return pd.concat(frames, ignore_index=True).sample(frac=1.0, random_state=seed).reset_index(drop=True)


BASE_PARAMS = {
    "n_estimators": 50,
    "learning_rate": 0.2,
    "num_leaves": 15,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "class_weight": "balanced",
    "n_jobs": 1,
    "verbose": -1,
}


def test_build_estimator_requires_balanced_class_weight():
    with pytest.raises(ValueError):
        build_estimator({**BASE_PARAMS, "class_weight": "none"}, seed=1)


def test_fit_model_rejects_target_leakage():
    df = _toy_df()
    with pytest.raises(ValueError):
        fit_model("m1", MODEL_FEATURES + ["y"], df, BASE_PARAMS, seed=42)


def test_m1_and_m2_train_and_predict():
    df = _toy_df()
    m1 = fit_model("m1", MODEL_FEATURES, df, BASE_PARAMS, seed=42)
    m2 = fit_model("m2", STRUCTURAL_FEATURES, df, BASE_PARAMS, seed=42)
    pred1 = m1.predict(df)
    pred2 = m2.predict(df)
    assert len(pred1) == len(df)
    assert len(pred2) == len(df)
    # Well-separated synthetic classes should be learnable near-perfectly.
    assert (pred1 == df["y"]).mean() > 0.9


def test_feature_importance_table_sums_consistently():
    df = _toy_df()
    m1 = fit_model("m1", MODEL_FEATURES, df, BASE_PARAMS, seed=42)
    table = feature_importance_table(m1)
    assert set(table["feature"]) == set(MODEL_FEATURES)
    assert np.isclose(table["share"].sum(), 1.0)
    assert (table["share"].diff().dropna() <= 1e-9).all()  # sorted descending


def test_clean_false_positive_rate():
    y_true = np.array([BENIGN_CODE, BENIGN_CODE, BENIGN_CODE, 1])
    y_pred = np.array([BENIGN_CODE, 1, 1, 1])
    out = clean_false_positive_rate(y_true, y_pred)
    assert out["n_benign"] == 3
    assert out["n_false_positive"] == 2
    assert np.isclose(out["clean_fpr"], 2 / 3)


def test_binary_attack_detection_recall():
    y_true = np.array([BENIGN_CODE, 1, 2, 3])
    y_pred = np.array([BENIGN_CODE, 1, BENIGN_CODE, 3])
    out = binary_attack_detection_recall(y_true, y_pred)
    assert out["n_attack"] == 3
    assert np.isclose(out["attack_detection_recall"], 2 / 3)


def test_clean_classification_report_flags_low_support():
    y_true = np.array([0] * 300 + [1] * 50 + [2] * 10 + [3] * 2)
    y_pred = y_true.copy()
    report = clean_classification_report(y_true, y_pred, low_support_threshold=200)
    row1 = report[report["project_class"] == "DDoS"].iloc[0]
    row0 = report[report["project_class"] == "Benign"].iloc[0]
    assert row1["low_support"]
    assert not row0["low_support"]


def test_confusion_matrix_table_shape():
    y_true = np.array([0, 1, 2, 3])
    y_pred = np.array([0, 1, 2, 0])
    cm = confusion_matrix_table(y_true, y_pred)
    assert cm.shape == (4, 4)
    assert cm.to_numpy().sum() == 4
