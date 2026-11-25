import numpy as np
import pandas as pd

from nids.data.label_mapping import BENIGN_CODE
from nids.features.feature_groups import DURATION_FEATURES, MODEL_FEATURES, RATE_FEATURES
from nids.features.ratios import compute_ratios
from nids.perturbation.pacing import perturb_attack_flows


def _flow_df(n=20, seed=0):
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


def test_benign_rows_completely_unchanged():
    df = _flow_df()
    df.loc[0, "y"] = BENIGN_CODE
    result = perturb_attack_flows(df, alpha_range=(1.5, 2.5), seed=42, rate_columns_scalable=[])
    benign_row = df.loc[0, MODEL_FEATURES]
    pert_row = result.perturbed.loc[0, MODEL_FEATURES]
    pd.testing.assert_series_equal(benign_row, pert_row, check_names=False)
    assert result.alpha[0] == 1.0


def test_attack_duration_scaled_by_alpha():
    df = _flow_df()
    df["y"] = 1  # all attack (DDoS)
    result = perturb_attack_flows(df, alpha_range=(2.0, 2.0), seed=1, rate_columns_scalable=[])
    for col in DURATION_FEATURES:
        expected = df[col].to_numpy() * 2.0
        np.testing.assert_allclose(result.perturbed[col].to_numpy(), expected)


def test_rate_columns_held_fixed_when_not_scalable():
    df = _flow_df()
    df["y"] = 2
    result = perturb_attack_flows(df, alpha_range=(1.5, 2.5), seed=5, rate_columns_scalable=[])
    for col in RATE_FEATURES:
        np.testing.assert_array_equal(df[col].to_numpy(), result.perturbed[col].to_numpy())


def test_rate_columns_scaled_by_inverse_alpha_when_approved():
    df = _flow_df()
    df["y"] = 2
    result = perturb_attack_flows(df, alpha_range=(2.0, 2.0), seed=5, rate_columns_scalable=["SRC_TO_DST_SECOND_BYTES"])
    expected = df["SRC_TO_DST_SECOND_BYTES"].to_numpy() / 2.0
    np.testing.assert_allclose(result.perturbed["SRC_TO_DST_SECOND_BYTES"].to_numpy(), expected)
    # Un-approved rate columns still held fixed.
    np.testing.assert_array_equal(df["DST_TO_SRC_SECOND_BYTES"].to_numpy(), result.perturbed["DST_TO_SRC_SECOND_BYTES"].to_numpy())


def test_structural_features_never_change_for_any_row():
    df = _flow_df()
    result = perturb_attack_flows(df, alpha_range=(1.5, 4.5), seed=7, rate_columns_scalable=[])
    from nids.features.feature_groups import STRUCTURAL_FEATURES

    for col in STRUCTURAL_FEATURES:
        np.testing.assert_array_equal(df[col].to_numpy(), result.perturbed[col].to_numpy())


def test_zero_duration_flow_is_not_perturbed():
    df = _flow_df()
    df["y"] = 1
    df.loc[3, "FLOW_DURATION_MILLISECONDS"] = 0
    df.loc[3, "DURATION_IN"] = 0
    df.loc[3, "DURATION_OUT"] = 0
    result = perturb_attack_flows(df, alpha_range=(2.0, 2.0), seed=11, rate_columns_scalable=[])
    assert result.is_zero_duration[3]
    for col in DURATION_FEATURES:
        assert result.perturbed.loc[3, col] == 0


def test_no_nan_or_negative_values_introduced():
    df = _flow_df()
    result = perturb_attack_flows(df, alpha_range=(1.5, 4.5), seed=3, rate_columns_scalable=["SRC_TO_DST_SECOND_BYTES"])
    arr = result.perturbed[MODEL_FEATURES].to_numpy()
    assert np.isfinite(arr).all()
    assert (arr >= 0).all()


def test_alpha_never_rounded_to_integer():
    df = _flow_df(n=200)
    df["y"] = 1
    result = perturb_attack_flows(df, alpha_range=(1.5, 2.5), seed=99, rate_columns_scalable=[])
    fractional = result.alpha[result.is_attack] % 1.0
    assert (fractional > 1e-9).any()  # at least some alphas are non-integer


def test_engineered_ratios_recomputed_and_invariant():
    df = _flow_df()
    df["y"] = 1
    result = perturb_attack_flows(df, alpha_range=(1.5, 4.5), seed=4, rate_columns_scalable=[])
    from nids.features.feature_groups import ENGINEERED_FEATURES

    np.testing.assert_allclose(
        df[ENGINEERED_FEATURES].to_numpy(), result.perturbed[ENGINEERED_FEATURES].to_numpy(), atol=1e-9
    )
