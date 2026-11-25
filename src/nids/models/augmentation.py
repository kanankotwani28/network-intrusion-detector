"""Training-set augmentation for M3 (Gaussian noise) and M4/M5 (adversarial
pacing), proposal Section 9 "M3/M4 — precise definition".

Both add exactly one synthetic copy of every *training* attack flow to the
clean training pool; Benign rows and the original attack rows are kept
unchanged. Neither ever touches test data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nids.data.label_mapping import BENIGN_CODE
from nids.features.feature_groups import ENGINEERED_FEATURES, NOISE_FEATURES
from nids.features.ratios import BinDenominator, compute_ratios
from nids.perturbation.pacing import perturb_attack_flows


def gaussian_noise_augment(train_df: pd.DataFrame, sigma: float, seed: int, label_col: str = "y") -> pd.DataFrame:
    """M3: clean pool + one noisy copy of every training attack flow.

    Noise is drawn in standardised space per continuous feature j:
    ``x' = x + eps``, ``eps ~ N(0, (sigma * s_j)^2)`` where ``s_j`` is that
    feature's *training-pool* standard deviation. Values are clipped at
    zero. Discrete columns (ports, protocol, flags, TTLs, ICMP/DNS/FTP
    codes) and all Benign rows are left untouched.
    """
    rng = np.random.default_rng(seed)
    attack_mask = train_df[label_col].to_numpy() != BENIGN_CODE
    noisy = train_df.loc[attack_mask].copy(deep=True).reset_index(drop=True)

    stds = train_df[NOISE_FEATURES].std(axis=0, ddof=0)
    for col in NOISE_FEATURES:
        s = float(stds[col])
        # A handful of pathological outliers in the rate/throughput columns
        # (Phase 1: these columns are already known to be unreliable in this
        # dataset -- see README 7a) can make the raw standard deviation
        # overflow to inf; such a column is held fixed, exactly like a
        # genuinely zero-variance one, rather than injecting unbounded noise.
        if not np.isfinite(s) or s <= 0:
            continue
        eps = rng.normal(loc=0.0, scale=sigma * s, size=len(noisy))
        noisy[col] = np.clip(noisy[col].to_numpy(dtype=np.float64) + eps, a_min=0.0, a_max=None)

    return pd.concat([train_df, noisy], axis=0, ignore_index=True)


def adversarial_pacing_augment(
    train_df: pd.DataFrame,
    alpha_range: tuple[float, float],
    seed: int,
    rate_columns_scalable: list[str],
    bin_denominator: BinDenominator = "in_out_pkts",
    label_col: str = "y",
) -> pd.DataFrame:
    """M4/M5 Layer 2: clean pool + one slowed copy of every training attack flow.

    Uses the same consistency-preserving pacing rule as the test-time
    perturbation (``alpha_train ~ U(1.5, 2.5)`` by default), applied only to
    training attack flows; engineered ratios (if present) are recomputed
    for the slowed copies.
    """
    result = perturb_attack_flows(
        train_df,
        alpha_range=alpha_range,
        seed=seed,
        rate_columns_scalable=rate_columns_scalable,
        label_col=label_col,
        bin_denominator=bin_denominator,
    )
    attack_mask = train_df[label_col].to_numpy() != BENIGN_CODE
    slowed = result.perturbed.loc[attack_mask].reset_index(drop=True)
    return pd.concat([train_df, slowed], axis=0, ignore_index=True)
