import numpy as np

from nids.data.label_mapping import BENIGN_CODE
from nids.evaluation.attack_evasion import attack_evasion_rate, post_perturbation_attack_recall


def test_aer_counts_only_benign_reclassification_as_evasion():
    # 4 attack flows detected clean (non-Benign); after perturbation: 1 -> Benign,
    # 1 -> a DIFFERENT attack class (not evasion), 2 stay correctly detected.
    y_true = np.array([1, 1, 1, 1])
    y_pred_clean = np.array([1, 1, 1, 1])  # all detected (D_m = all 4)
    y_pred_pert = np.array([BENIGN_CODE, 2, 1, 1])  # reclassified to class 2 is NOT evasion
    out = attack_evasion_rate(y_true, y_pred_clean, y_pred_pert)
    assert out["n_detected_clean"] == 4
    assert out["n_evaded"] == 1
    assert np.isclose(out["aer"], 25.0)


def test_aer_denominator_is_only_clean_detected_flows():
    y_true = np.array([1, 1, 1])
    y_pred_clean = np.array([1, BENIGN_CODE, 1])  # only 2 detected clean
    y_pred_pert = np.array([BENIGN_CODE, BENIGN_CODE, 1])
    out = attack_evasion_rate(y_true, y_pred_clean, y_pred_pert)
    assert out["n_detected_clean"] == 2
    assert out["n_evaded"] == 1
    assert np.isclose(out["aer"], 50.0)


def test_aer_nan_when_denominator_zero():
    y_true = np.array([1, 1])
    y_pred_clean = np.array([BENIGN_CODE, BENIGN_CODE])
    y_pred_pert = np.array([BENIGN_CODE, BENIGN_CODE])
    out = attack_evasion_rate(y_true, y_pred_clean, y_pred_pert)
    assert out["n_detected_clean"] == 0
    assert np.isnan(out["aer"])


def test_post_perturbation_recall_over_entire_attack_set():
    # Includes a flow missed even on clean data (not in D_m) -- still counted here.
    y_true = np.array([1, 1, 1])
    y_pred_pert = np.array([1, BENIGN_CODE, BENIGN_CODE])
    out = post_perturbation_attack_recall(y_true, y_pred_pert)
    assert out["n_attack"] == 3
    assert np.isclose(out["post_perturbation_recall"], 1 / 3)


def test_aer_restricted_to_class():
    y_true = np.array([1, 1, 2, 2])
    y_pred_clean = np.array([1, 1, 2, 2])
    y_pred_pert = np.array([BENIGN_CODE, 1, BENIGN_CODE, BENIGN_CODE])
    ddos = attack_evasion_rate(y_true, y_pred_clean, y_pred_pert, class_code=1)
    dos = attack_evasion_rate(y_true, y_pred_clean, y_pred_pert, class_code=2)
    assert np.isclose(ddos["aer"], 50.0)
    assert np.isclose(dos["aer"], 100.0)
