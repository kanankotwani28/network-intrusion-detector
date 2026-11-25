import numpy as np
import pandas as pd

from nids.data.label_mapping import BENIGN_CODE
from nids.features.feature_groups import DISCRETE_FEATURES, DURATION_FEATURES, MODEL_FEATURES, NOISE_FEATURES
from nids.features.ratios import compute_ratios
from nids.models.augmentation import adversarial_pacing_augment, gaussian_noise_augment


def _flow_df(n=40, seed=0):
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


def test_gaussian_noise_doubles_only_attack_rows():
    df = _flow_df()
    n_attack = int((df["y"] != BENIGN_CODE).sum())
    n_benign = int((df["y"] == BENIGN_CODE).sum())
    out = gaussian_noise_augment(df, sigma=0.10, seed=1)
    assert len(out) == len(df) + n_attack
    assert int((out["y"] == BENIGN_CODE).sum()) == n_benign  # no benign rows added


def test_gaussian_noise_leaves_discrete_features_identical():
    df = _flow_df()
    out = gaussian_noise_augment(df, sigma=0.10, seed=1)
    noisy_copies = out.iloc[len(df):]
    original_attacks = df[df["y"] != BENIGN_CODE].reset_index(drop=True)
    for col in DISCRETE_FEATURES:
        if col in ("y",):
            continue
        np.testing.assert_array_equal(original_attacks[col].to_numpy(), noisy_copies[col].to_numpy())


def test_gaussian_noise_clips_at_zero_and_stays_finite():
    df = _flow_df()
    out = gaussian_noise_augment(df, sigma=0.10, seed=1)
    arr = out[NOISE_FEATURES].to_numpy()
    assert np.isfinite(arr).all()
    assert (arr >= 0).all()


def test_gaussian_noise_skips_column_with_infinite_std_from_outlier():
    df = _flow_df()
    # One pathological outlier (mirrors a real data-quality finding: some
    # rate columns in this dataset contain astronomically large values)
    # must not blow up std() to inf and inject unbounded noise everywhere.
    df.loc[0, "SRC_TO_DST_SECOND_BYTES"] = 1e250
    out = gaussian_noise_augment(df, sigma=0.10, seed=1)
    assert np.isfinite(out["SRC_TO_DST_SECOND_BYTES"].to_numpy()).all()


def test_adversarial_pacing_augment_doubles_attack_rows_and_scales_duration():
    df = _flow_df()
    n_attack = int((df["y"] != BENIGN_CODE).sum())
    out = adversarial_pacing_augment(df, alpha_range=(2.0, 2.0), seed=2, rate_columns_scalable=[])
    assert len(out) == len(df) + n_attack
    slowed = out.iloc[len(df):].reset_index(drop=True)
    original_attacks = df[df["y"] != BENIGN_CODE].reset_index(drop=True)
    for col in DURATION_FEATURES:
        np.testing.assert_allclose(slowed[col].to_numpy(), original_attacks[col].to_numpy() * 2.0)
