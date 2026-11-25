"""M5 SHAP-guided feature selection (proposal Section 10, Appendix D/F).

Procedure (deterministic, run once, then frozen and reused for all 5 seeds):

1. M1 (already trained on the full clean training pool, seed 42) is the
   diagnosed model.
2. A class-capped subset (<=2,500 flows/class, seed 42) of the *training*
   pool is explained with ``shap.TreeExplainer`` in raw margin space.
3. Importance share ``I_j = mean(|phi_j|) / sum_k mean(|phi_k|)``, averaged
   over the subset and classes.
4. A candidate timing/rate column is "fragile" if ``I_j >= threshold``
   (``1/p``, p=40, so 0.025 by default); flagged columns are dropped from
   M5's feature layer, unflagged ones are kept alongside the 8 engineered
   ratios.
5. Sensitivity thresholds (0.01, 0.05) are reported alongside, without
   changing which list gets frozen.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap

from nids.data.label_mapping import PROJECT_CLASSES
from nids.features.feature_groups import ENGINEERED_FEATURES, MODEL_FEATURES, STRUCTURAL_FEATURES, TIMING_FEATURES
from nids.models.base import TrainedModel


def class_capped_subset(df: pd.DataFrame, label_col: str, cap_per_class: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    parts = []
    for code, grp in df.groupby(label_col, sort=True):
        n = min(cap_per_class, len(grp))
        idx = rng.choice(grp.index.to_numpy(), size=n, replace=False)
        parts.append(df.loc[idx])
    return pd.concat(parts, axis=0).reset_index(drop=True)


def compute_importance_shares(m1: TrainedModel, subset: pd.DataFrame) -> pd.DataFrame:
    """Return per-feature importance share I_j, averaged over classes and rows."""
    explainer = shap.TreeExplainer(m1.estimator, model_output="raw")
    shap_values = explainer.shap_values(subset[m1.feature_list])
    # LightGBM multiclass TreeExplainer: list of (n_samples, n_features) per class,
    # or a single (n_samples, n_features, n_classes) array depending on shap version.
    if isinstance(shap_values, list):
        per_class_mean_abs = np.stack([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0)
    else:
        arr = np.asarray(shap_values)
        if arr.ndim == 3:
            per_class_mean_abs = np.abs(arr).mean(axis=0).T  # (n_classes, n_features)
        else:
            per_class_mean_abs = np.abs(arr).mean(axis=0, keepdims=True)
    mean_abs_overall = per_class_mean_abs.mean(axis=0)  # average over classes
    total = mean_abs_overall.sum()
    shares = mean_abs_overall / total if total > 0 else np.zeros_like(mean_abs_overall)
    return pd.DataFrame({"feature": m1.feature_list, "importance_share": shares}).sort_values(
        "importance_share", ascending=False
    ).reset_index(drop=True)


@dataclass
class M5SelectionResult:
    importance_table: pd.DataFrame
    flagged_fragile: list[str]
    retained_timing: list[str]
    feature_list: list[str]
    sensitivity: pd.DataFrame


def select_m5_features(
    m1: TrainedModel,
    train_df: pd.DataFrame,
    label_col: str,
    threshold: float,
    sensitivity_thresholds: list[float],
    cap_per_class: int,
    seed: int,
) -> M5SelectionResult:
    subset = class_capped_subset(train_df, label_col, cap_per_class, seed)
    importance = compute_importance_shares(m1, subset)

    timing_importance = importance[importance["feature"].isin(TIMING_FEATURES)]
    flagged = timing_importance.loc[timing_importance["importance_share"] >= threshold, "feature"].tolist()
    retained_timing = [c for c in TIMING_FEATURES if c not in flagged]

    feature_list = STRUCTURAL_FEATURES + retained_timing + ENGINEERED_FEATURES

    sens_rows = []
    for thr in sensitivity_thresholds:
        flagged_at_thr = timing_importance.loc[timing_importance["importance_share"] >= thr, "feature"].tolist()
        sens_rows.append(
            {
                "threshold": thr,
                "n_flagged": len(flagged_at_thr),
                "flagged_features": ";".join(flagged_at_thr),
            }
        )
    sensitivity = pd.DataFrame(sens_rows)

    importance_out = importance.copy()
    importance_out["group"] = np.where(
        importance_out["feature"].isin(TIMING_FEATURES), "timing_rate", "structural"
    )
    importance_out["fragile_at_main_threshold"] = importance_out["feature"].isin(flagged)

    return M5SelectionResult(
        importance_table=importance_out,
        flagged_fragile=flagged,
        retained_timing=retained_timing,
        feature_list=feature_list,
        sensitivity=sensitivity,
    )
