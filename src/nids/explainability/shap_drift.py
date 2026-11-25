"""Non-circular forensic SHAP attribution-drift audit (proposal Stage 4).

Audit set A is defined using M1 alone (clean test flows M1 detects as
non-Benign, that flip to Benign after OOD perturbation), *never* using M4
or M5's predictions, and every flow is explained for its ground-truth
class, never its predicted class -- both are what make the audit
non-circular. The same flow IDs are then explained for M1, M4 and M5.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap

from nids.data.label_mapping import ATTACK_CODES, BENIGN_CODE, PROJECT_CLASSES
from nids.features.feature_groups import ENGINEERED_FEATURES, TIMING_FEATURES
from nids.models.base import TrainedModel


@dataclass
class AuditSample:
    indices: np.ndarray  # positional indices into the clean test frame
    true_class: np.ndarray
    substituted_classes: list[str]  # classes where <30 evaded flows forced a substitution


def build_audit_sample(
    y_true: np.ndarray,
    y_pred_clean_m1: np.ndarray,
    y_pred_ood_m1: np.ndarray,
    cap_per_class: int,
    min_evaded: int,
    seed: int,
) -> AuditSample:
    """Baseline-evaded flows per Section 16, with the documented fallback."""
    rng = np.random.default_rng(seed)
    detected_clean = y_pred_clean_m1 != BENIGN_CODE
    evaded = detected_clean & (y_pred_ood_m1 == BENIGN_CODE)

    chosen: list[np.ndarray] = []
    substituted: list[str] = []
    for code in ATTACK_CODES:
        class_mask = y_true == code
        evaded_idx = np.flatnonzero(class_mask & evaded)
        if len(evaded_idx) >= min_evaded:
            pool = evaded_idx
        else:
            # Fallback: 300 randomly drawn clean-detected flows of that class.
            pool = np.flatnonzero(class_mask & detected_clean)
            substituted.append(PROJECT_CLASSES[code])
        n = min(cap_per_class, len(pool))
        if n == 0:
            continue
        chosen.append(rng.choice(pool, size=n, replace=False))

    indices = np.concatenate(chosen) if chosen else np.array([], dtype=np.int64)
    return AuditSample(indices=indices, true_class=y_true[indices], substituted_classes=substituted)


def _ground_truth_shap(model: TrainedModel, X: pd.DataFrame, true_class: np.ndarray) -> np.ndarray:
    """phi_j(x, true_class) for every row -- its OWN ground-truth class, not predicted."""
    explainer = shap.TreeExplainer(model.estimator, model_output="raw")
    shap_values = explainer.shap_values(X[model.feature_list])
    if isinstance(shap_values, list):
        stacked = np.stack(shap_values, axis=-1)  # (n, n_features, n_classes)
    else:
        arr = np.asarray(shap_values)
        stacked = arr if arr.ndim == 3 else arr[..., np.newaxis]
    n = len(X)
    out = np.empty((n, stacked.shape[1]), dtype=np.float64)
    for i in range(n):
        out[i] = stacked[i, :, true_class[i]]
    return out


def audit_attribution_drift(
    model: TrainedModel,
    clean_test: pd.DataFrame,
    perturbed_test: pd.DataFrame,
    audit: AuditSample,
) -> pd.DataFrame:
    """Per-flow, per-feature attribution shift Delta_phi_j for one model."""
    X_clean = clean_test.iloc[audit.indices]
    X_pert = perturbed_test.iloc[audit.indices]
    phi_clean = _ground_truth_shap(model, X_clean, audit.true_class)
    phi_pert = _ground_truth_shap(model, X_pert, audit.true_class)
    delta = phi_pert - phi_clean

    rows = []
    for i, feat in enumerate(model.feature_list):
        rows.append(
            {
                "model": model.name,
                "feature": feat,
                "group": _feature_group(feat, model.name),
                "mean_signed_shift": float(delta[:, i].mean()),
                "mean_abs_phi_clean": float(np.abs(phi_clean[:, i]).mean()),
                "mean_abs_phi_perturbed": float(np.abs(phi_pert[:, i]).mean()),
            }
        )
    df = pd.DataFrame(rows)
    total_clean = df["mean_abs_phi_clean"].sum()
    total_pert = df["mean_abs_phi_perturbed"].sum()
    df["attribution_share_clean"] = df["mean_abs_phi_clean"] / total_clean if total_clean > 0 else 0.0
    df["attribution_share_perturbed"] = df["mean_abs_phi_perturbed"] / total_pert if total_pert > 0 else 0.0
    df["delta_attribution_share"] = df["attribution_share_perturbed"] - df["attribution_share_clean"]
    df["n_audited_flows"] = len(audit.indices)
    return df


def _feature_group(feature: str, model_name: str) -> str:
    if feature in ENGINEERED_FEATURES:
        return "engineered_invariant"
    if feature in TIMING_FEATURES:
        return "fragile_timing_rate"
    return "other_structural"


def group_summary(drift_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Aggregate Delta_G per model and feature group (Section 16 "Reported groups")."""
    rows = []
    for model_name, df in drift_tables.items():
        for group, grp in df.groupby("group"):
            rows.append(
                {
                    "model": model_name,
                    "group": group,
                    "n_features": len(grp),
                    "mean_signed_shift": grp["mean_signed_shift"].mean(),
                    "attribution_share_clean": grp["attribution_share_clean"].sum(),
                    "attribution_share_perturbed": grp["attribution_share_perturbed"].sum(),
                    "delta_attribution_share": grp["delta_attribution_share"].sum(),
                    "n_audited_flows": int(grp["n_audited_flows"].iloc[0]) if len(grp) else 0,
                }
            )
    return pd.DataFrame(rows)
