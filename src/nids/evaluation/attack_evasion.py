"""Attack Evasion Rate and post-perturbation recall (proposal Appendix E)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nids.data.label_mapping import ATTACK_CODES, BENIGN_CODE, PROJECT_CLASSES


def attack_evasion_rate(
    y_true_clean: np.ndarray,
    y_pred_clean: np.ndarray,
    y_pred_perturbed: np.ndarray,
    class_code: int | None = None,
) -> dict:
    """AER_m = |{flows in D_m predicted Benign after perturbation}| / |D_m| * 100.

    D_m = attack flows the model predicts as non-Benign on the clean test
    set (restricted to ``class_code`` if given). Reclassification into a
    *different* attack class does not count as evasion -- only a
    post-perturbation prediction of Benign does.
    """
    attack_mask = y_true_clean != BENIGN_CODE
    if class_code is not None:
        attack_mask &= y_true_clean == class_code
    detected_clean = attack_mask & (y_pred_clean != BENIGN_CODE)  # D_m
    denom = int(detected_clean.sum())
    if denom == 0:
        return {"aer": float("nan"), "n_detected_clean": 0, "n_evaded": 0}
    evaded = int(np.sum(detected_clean & (y_pred_perturbed == BENIGN_CODE)))
    return {"aer": evaded / denom * 100.0, "n_detected_clean": denom, "n_evaded": evaded}


def post_perturbation_attack_recall(y_true_clean: np.ndarray, y_pred_perturbed: np.ndarray, class_code: int | None = None) -> dict:
    """Recall over the ENTIRE perturbed attack test set (not just D_m)."""
    attack_mask = y_true_clean != BENIGN_CODE
    if class_code is not None:
        attack_mask &= y_true_clean == class_code
    n = int(attack_mask.sum())
    if n == 0:
        return {"post_perturbation_recall": float("nan"), "n_attack": 0}
    detected = int(np.sum(attack_mask & (y_pred_perturbed != BENIGN_CODE)))
    return {"post_perturbation_recall": detected / n, "n_attack": n}


def aer_by_class(
    y_true_clean: np.ndarray,
    y_pred_clean: np.ndarray,
    y_pred_perturbed: np.ndarray,
    is_zero_duration: np.ndarray | None = None,
    low_support_threshold: int = 200,
) -> pd.DataFrame:
    """Overall + per-attack-class AER and post-perturbation recall, with
    sample counts and a low-support flag, plus the positive-duration-only
    supplementary AER (proposal Section 15)."""
    rows = []
    for label, code in [("overall", None)] + [(PROJECT_CLASSES[c], c) for c in ATTACK_CODES]:
        aer = attack_evasion_rate(y_true_clean, y_pred_clean, y_pred_perturbed, code)
        recall = post_perturbation_attack_recall(y_true_clean, y_pred_perturbed, code)
        row = {"class": label, **aer, **recall}
        row["low_support"] = row["n_detected_clean"] < low_support_threshold
        rows.append(row)

        if is_zero_duration is not None and label == "overall":
            pos_dur_mask = ~is_zero_duration
            attack_mask = y_true_clean != BENIGN_CODE
            detected_clean = attack_mask & (y_pred_clean != BENIGN_CODE) & pos_dur_mask
            denom = int(detected_clean.sum())
            if denom > 0:
                evaded = int(np.sum(detected_clean & (y_pred_perturbed == BENIGN_CODE)))
                rows.append(
                    {
                        "class": "overall_positive_duration_only",
                        "aer": evaded / denom * 100.0,
                        "n_detected_clean": denom,
                        "n_evaded": evaded,
                        "post_perturbation_recall": float("nan"),
                        "n_attack": float("nan"),
                        "low_support": denom < low_support_threshold,
                    }
                )
    return pd.DataFrame(rows)
