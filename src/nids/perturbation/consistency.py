"""Perturbation consistency verification (proposal Section 13).

Checks every invariant the pacing perturbation must satisfy and produces
the ``perturbation_consistency_check.csv`` report. These are hard
correctness checks on the perturbation *code*, independent of whether a
rate column happened to pass Phase 1's identity check -- a column this
dataset held fixed must still come back out byte-identical, which is
itself verified here as check #4/#5.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nids.data.label_mapping import BENIGN_CODE
from nids.features.feature_groups import (
    DURATION_FEATURES,
    ENGINEERED_FEATURES,
    MODEL_FEATURES,
    RATE_FEATURES,
    STRUCTURAL_FEATURES,
)
from nids.perturbation.pacing import PerturbationResult


def _row(check: str, target: str, passed: bool, detail: str = "") -> dict:
    return {"check": check, "target": target, "passed": bool(passed), "detail": detail}


def verify_perturbation(
    clean: pd.DataFrame,
    result: PerturbationResult,
    rate_columns_scalable: list[str],
    relative_tolerance: float,
    min_pass_rate: float,
    label_col: str = "y",
) -> pd.DataFrame:
    rows: list[dict] = []
    perturbed = result.perturbed
    alpha = result.alpha
    is_attack = result.is_attack

    # 1/2. Structural features (incl. bytes, packets) byte-identical for every row.
    for col in STRUCTURAL_FEATURES:
        if col not in clean.columns:
            continue
        eq = np.array_equal(clean[col].to_numpy(), perturbed[col].to_numpy())
        rows.append(_row("structural_feature_unchanged", col, eq))

    # 3. Durations scale correctly: x' == alpha*x (incl. zero-duration -> 0).
    for col in DURATION_FEATURES:
        expected = clean[col].to_numpy(dtype=np.float64) * alpha
        close = np.allclose(perturbed[col].to_numpy(dtype=np.float64), expected, rtol=0, atol=1e-6)
        rows.append(_row("duration_scales_by_alpha", col, close))

    # 4. Rate columns: scaled by 1/alpha if approved, else held fixed exactly.
    for col in RATE_FEATURES:
        if col in rate_columns_scalable:
            expected = clean[col].to_numpy(dtype=np.float64) / alpha
            close = np.allclose(perturbed[col].to_numpy(dtype=np.float64), expected, rtol=0, atol=1e-9)
            rows.append(_row("rate_scales_by_inverse_alpha", col, close))
        else:
            eq = np.array_equal(clean[col].to_numpy(), perturbed[col].to_numpy())
            rows.append(_row("rate_held_fixed_as_failed_column", col, eq))

    # 5. Rate * duration product constant, for approved (rate, duration) pairs only.
    pairing = {
        "SRC_TO_DST_SECOND_BYTES": "DURATION_IN",
        "DST_TO_SRC_SECOND_BYTES": "DURATION_OUT",
        "SRC_TO_DST_AVG_THROUGHPUT": "DURATION_IN",
        "DST_TO_SRC_AVG_THROUGHPUT": "DURATION_OUT",
    }
    if not rate_columns_scalable:
        rows.append(_row("rate_duration_product_constant", "all", True, "no rate column passed Phase 1 verification; nothing to check"))
    for rc, dc in pairing.items():
        if rc not in rate_columns_scalable:
            continue
        dur = clean[dc].to_numpy(dtype=np.float64)
        pos = dur > 0
        prod_clean = clean[rc].to_numpy(dtype=np.float64)[pos] * dur[pos]
        prod_pert = perturbed[rc].to_numpy(dtype=np.float64)[pos] * (dur[pos] * alpha[pos])
        ok = relation_within_tolerance(prod_clean, prod_pert, relative_tolerance)
        rows.append(_row("rate_duration_product_constant", rc, ok.mean() >= min_pass_rate, f"pass_rate={ok.mean():.4f}"))

    # 6. Engineered ratios unchanged (they depend only on fixed bytes/packets).
    for col in ENGINEERED_FEATURES:
        if col not in clean.columns:
            continue
        close = np.allclose(clean[col].to_numpy(dtype=np.float64), perturbed[col].to_numpy(dtype=np.float64), rtol=1e-9, atol=1e-9)
        rows.append(_row("engineered_ratio_invariant", col, close))

    # 7. Benign rows completely untouched (every model column, exact).
    benign_mask = clean[label_col].to_numpy() == BENIGN_CODE
    all_cols = [c for c in MODEL_FEATURES if c in clean.columns]
    benign_eq = np.array_equal(clean.loc[benign_mask, all_cols].to_numpy(), perturbed.loc[benign_mask, all_cols].to_numpy())
    rows.append(_row("benign_rows_untouched", "all_model_features", benign_eq, f"n_benign={int(benign_mask.sum())}"))

    # 8. Zero-duration flows: perturbed duration must equal clean duration (both 0).
    zd = result.is_zero_duration
    if zd.any():
        zd_eq = np.array_equal(clean.loc[zd, DURATION_FEATURES].to_numpy(), perturbed.loc[zd, DURATION_FEATURES].to_numpy())
    else:
        zd_eq = True
    rows.append(_row("zero_duration_flows_unchanged", "duration_columns", zd_eq, f"n_zero_duration_attack_flows={int(zd.sum())}"))

    # 9. No NaN/Inf introduced anywhere in the model feature matrix.
    present = [c for c in MODEL_FEATURES if c in perturbed.columns]
    finite = np.isfinite(perturbed[present].to_numpy(dtype=np.float64)).all()
    rows.append(_row("no_nan_or_inf_introduced", "all_model_features", finite))

    # Alpha sanity: no negative or impossible values, attack rows only.
    rows.append(_row("alpha_within_configured_range_for_attacks", "alpha", bool(np.all(alpha[is_attack] >= 1.0))))

    return pd.DataFrame(rows)


def relation_within_tolerance(a: np.ndarray, b: np.ndarray, tol: float) -> np.ndarray:
    out = np.zeros(a.shape, dtype=bool)
    zero = a == 0
    out[zero] = b[zero] == 0
    nz = ~zero
    out[nz] = np.abs(a[nz] - b[nz]) <= tol * np.abs(a[nz])
    return out
