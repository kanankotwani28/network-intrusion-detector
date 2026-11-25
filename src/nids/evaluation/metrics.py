"""Evaluation metric definitions (proposal Appendix E)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix as sk_confusion_matrix
from sklearn.metrics import precision_recall_fscore_support

from nids.data.label_mapping import BENIGN_CODE, PROJECT_CLASSES


def clean_classification_report(y_true: np.ndarray, y_pred: np.ndarray, low_support_threshold: int = 200) -> pd.DataFrame:
    """Per-class precision/recall/F1 + macro/weighted F1, with support and a
    low-support flag (proposal Section 15: never hide a weak/unstable class).
    """
    labels = list(range(len(PROJECT_CLASSES)))
    p, r, f1, support = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    rows = [
        {
            "project_class": PROJECT_CLASSES[i],
            "precision": p[i],
            "recall": r[i],
            "f1": f1[i],
            "support": int(support[i]),
            "low_support": int(support[i]) < low_support_threshold,
        }
        for i in labels
    ]
    macro_f1 = float(np.mean(f1))
    weighted_f1 = float(np.average(f1, weights=support)) if support.sum() > 0 else 0.0
    rows.append({"project_class": "MACRO", "precision": np.nan, "recall": np.nan, "f1": macro_f1, "support": int(support.sum()), "low_support": False})
    rows.append({"project_class": "WEIGHTED", "precision": np.nan, "recall": np.nan, "f1": weighted_f1, "support": int(support.sum()), "low_support": False})
    return pd.DataFrame(rows)


def confusion_matrix_table(y_true: np.ndarray, y_pred: np.ndarray) -> pd.DataFrame:
    labels = list(range(len(PROJECT_CLASSES)))
    cm = sk_confusion_matrix(y_true, y_pred, labels=labels)
    return pd.DataFrame(cm, index=[f"true_{c}" for c in PROJECT_CLASSES], columns=[f"pred_{c}" for c in PROJECT_CLASSES])


def clean_false_positive_rate(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Benign flows predicted as any attack class, over all Benign flows."""
    benign_mask = y_true == BENIGN_CODE
    n_benign = int(benign_mask.sum())
    if n_benign == 0:
        return {"clean_fpr": float("nan"), "n_benign": 0, "n_false_positive": 0}
    fp = int(np.sum(benign_mask & (y_pred != BENIGN_CODE)))
    return {"clean_fpr": fp / n_benign, "n_benign": n_benign, "n_false_positive": fp}


def binary_attack_detection_recall(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Recall of (attack vs Benign) over the clean attack test flows."""
    attack_mask = y_true != BENIGN_CODE
    n_attack = int(attack_mask.sum())
    if n_attack == 0:
        return {"attack_detection_recall": float("nan"), "n_attack": 0}
    detected = int(np.sum(attack_mask & (y_pred != BENIGN_CODE)))
    return {"attack_detection_recall": detected / n_attack, "n_attack": n_attack}


def summarize_clean_performance(model_name: str, seed: int, y_true: np.ndarray, y_pred: np.ndarray, low_support_threshold: int = 200) -> dict:
    report = clean_classification_report(y_true, y_pred, low_support_threshold)
    fpr = clean_false_positive_rate(y_true, y_pred)
    recall = binary_attack_detection_recall(y_true, y_pred)
    macro_f1 = report.loc[report["project_class"] == "MACRO", "f1"].iloc[0]
    weighted_f1 = report.loc[report["project_class"] == "WEIGHTED", "f1"].iloc[0]
    return {
        "model": model_name,
        "seed": seed,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        **fpr,
        **recall,
    }
