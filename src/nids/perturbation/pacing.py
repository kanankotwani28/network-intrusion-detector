"""Consistency-preserving traffic-pacing perturbation (proposal Appendix C).

Only attack flows are perturbed; Benign flows are returned byte-identical.
For each attack flow an independent stretch factor ``alpha ~ U(lo, hi)`` is
drawn, and:

- the 3 duration columns are multiplied by alpha (a zero duration stays
  zero: ``0 * alpha == 0``, so such flows are "perturbed" in name only);
- a rate/throughput column is divided by alpha **only if** Phase 1's
  empirical identity check approved it for that treatment
  (``rate_columns_scalable``) -- for this dataset that list is empty (see
  README Section 7a), so by default all four rate columns are held fixed,
  exactly as Appendix C's fallback rule requires for a column that fails
  verification;
- every other column (all structural features) is left exactly unchanged.

Engineered ratios (if present as columns) are recomputed afterwards from
the perturbed bytes/packets, though since those never change under this
rule the recomputation is a no-op -- it is kept anyway to remove any doubt
and to make the function correct even if a future dataset's identity check
does approve some rate columns for scaling (which would still never affect
bytes/packets, so ratios remain invariant either way).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nids.data.label_mapping import BENIGN_CODE
from nids.features.feature_groups import DURATION_FEATURES, ENGINEERED_FEATURES, RATE_FEATURES
from nids.features.ratios import BinDenominator, compute_ratios


@dataclass
class PerturbationResult:
    perturbed: pd.DataFrame
    alpha: np.ndarray  # 1.0 for untouched (Benign or zero-duration) rows
    is_attack: np.ndarray
    is_zero_duration: np.ndarray


def perturb_attack_flows(
    df: pd.DataFrame,
    alpha_range: tuple[float, float],
    seed: int,
    rate_columns_scalable: list[str],
    label_col: str = "y",
    bin_denominator: BinDenominator = "in_out_pkts",
) -> PerturbationResult:
    """Apply the consistency-preserving pacing perturbation to attack flows.

    Returns a new DataFrame (the input is never modified in place) plus the
    alpha actually applied to each row (``1.0`` where nothing changed).
    """
    lo, hi = alpha_range
    out = df.copy(deep=True)
    n = len(df)
    rng = np.random.default_rng(seed)

    is_attack = (df[label_col].to_numpy() != BENIGN_CODE)
    alpha = np.ones(n, dtype=np.float64)
    alpha[is_attack] = rng.uniform(lo, hi, size=int(is_attack.sum()))

    flow_ms = df["FLOW_DURATION_MILLISECONDS"].to_numpy(dtype=np.float64)
    is_zero_duration = is_attack & (flow_ms == 0)

    for col in DURATION_FEATURES:
        out[col] = df[col].to_numpy(dtype=np.float64) * alpha

    for col in RATE_FEATURES:
        if col in rate_columns_scalable:
            out[col] = df[col].to_numpy(dtype=np.float64) / alpha
        # else: held fixed at its original value (Appendix C fallback rule).

    if all(c in out.columns for c in ENGINEERED_FEATURES):
        out[ENGINEERED_FEATURES] = compute_ratios(out, bin_denominator=bin_denominator)

    return PerturbationResult(perturbed=out, alpha=alpha, is_attack=is_attack, is_zero_duration=is_zero_duration)


def load_rate_columns_scalable(rate_identity_decision: dict) -> list[str]:
    """Extract the approved-for-scaling rate columns from Phase 1's decision dict."""
    return list(rate_identity_decision.get("rate_columns_scalable", []))
