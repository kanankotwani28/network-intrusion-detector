import numpy as np
import pandas as pd

from nids.features.feature_groups import MODEL_FEATURES
from nids.features.ratios import compute_ratios
from nids.perturbation.consistency import verify_perturbation
from nids.perturbation.pacing import perturb_attack_flows


def _flow_df(n=50, seed=0):
    rng = np.random.default_rng(seed)
    data = {f: np.abs(rng.integers(1, 1000, size=n)).astype(np.float64) for f in MODEL_FEATURES}
    df = pd.DataFrame(data)
    df["y"] = rng.integers(0, 4, size=n)
    for c in ["IN_PKTS", "OUT_PKTS"] + [c for c in MODEL_FEATURES if c.startswith("NUM_PKTS")]:
        df[c] = np.abs(rng.integers(1, 50, size=n)).astype(np.float64)
    ratios = compute_ratios(df)
    for c in ratios.columns:
        df[c] = ratios[c]
    return df


def test_all_checks_pass_with_no_scalable_rate_columns():
    df = _flow_df()
    result = perturb_attack_flows(df, alpha_range=(1.5, 2.5), seed=42, rate_columns_scalable=[])
    report = verify_perturbation(df, result, rate_columns_scalable=[], relative_tolerance=0.05, min_pass_rate=0.95)
    assert report["passed"].all(), report[~report["passed"]].to_string()


def test_all_checks_pass_with_a_scalable_rate_column():
    df = _flow_df()
    result = perturb_attack_flows(df, alpha_range=(1.5, 2.5), seed=42, rate_columns_scalable=["SRC_TO_DST_SECOND_BYTES"])
    report = verify_perturbation(
        df, result, rate_columns_scalable=["SRC_TO_DST_SECOND_BYTES"], relative_tolerance=0.05, min_pass_rate=0.95
    )
    assert report["passed"].all(), report[~report["passed"]].to_string()


def test_broken_perturbation_is_caught():
    df = _flow_df()
    result = perturb_attack_flows(df, alpha_range=(1.5, 2.5), seed=42, rate_columns_scalable=[])
    # Sabotage: alter a structural feature in the perturbed copy.
    result.perturbed.loc[0, "L4_DST_PORT"] = result.perturbed.loc[0, "L4_DST_PORT"] + 1
    report = verify_perturbation(df, result, rate_columns_scalable=[], relative_tolerance=0.05, min_pass_rate=0.95)
    failing = report[(report["check"] == "structural_feature_unchanged") & (report["target"] == "L4_DST_PORT")]
    assert not failing["passed"].iloc[0]
