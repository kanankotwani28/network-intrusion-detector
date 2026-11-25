"""Engineered timing-invariant ratios (Appendix D "EN", M5 only).

The packet-size-bin denominator is an empirical fact about the dataset
(Phase 1, ``rate_identity_decision.json``: this dataset's five
``NUM_PKTS_*`` bins sum to ``IN_PKTS + OUT_PKTS``, not ``IN_PKTS`` alone),
so it is a parameter here rather than hardcoded, with ``"in_pkts"`` as the
fallback for datasets where only the single-direction convention holds.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from nids.features.feature_groups import ENGINEERED_FEATURES, PACKET_SIZE_BIN_FEATURES

BinDenominator = Literal["in_pkts", "in_out_pkts"]


def compute_ratios(df: pd.DataFrame, bin_denominator: BinDenominator = "in_out_pkts") -> pd.DataFrame:
    """Return the 8 engineered ratio columns computed from raw features.

    Zero denominators never produce NaN/Inf: ``IN_PKTS``/``OUT_PKTS`` are
    floored at 1 inside ``BPP_IN``/``BPP_OUT``/the bin shares (the proposal's
    rule), and ``DIR_RATIO``'s denominator always has ``+ 1`` so it is never
    zero.
    """
    in_bytes = df["IN_BYTES"].to_numpy(dtype=np.float64)
    out_bytes = df["OUT_BYTES"].to_numpy(dtype=np.float64)
    in_pkts = df["IN_PKTS"].to_numpy(dtype=np.float64)
    out_pkts = df["OUT_PKTS"].to_numpy(dtype=np.float64)

    out = pd.DataFrame(index=df.index)
    out["BPP_IN"] = in_bytes / np.maximum(in_pkts, 1.0)
    out["BPP_OUT"] = out_bytes / np.maximum(out_pkts, 1.0)
    out["DIR_RATIO"] = in_bytes / (out_bytes + 1.0)

    if bin_denominator == "in_out_pkts":
        denom = np.maximum(in_pkts + out_pkts, 1.0)
    else:
        denom = np.maximum(in_pkts, 1.0)

    share_names = ["SHARE_128", "SHARE_128_256", "SHARE_256_512", "SHARE_512_1024", "SHARE_1024_1514"]
    for name, col in zip(share_names, PACKET_SIZE_BIN_FEATURES):
        out[name] = df[col].to_numpy(dtype=np.float64) / denom

    out = out[ENGINEERED_FEATURES]
    assert np.isfinite(out.to_numpy()).all(), "engineered ratios must never be NaN/Inf"
    assert (out.to_numpy() >= -1e-9).all(), "engineered ratios must never be negative"
    return out


def attach_ratios(df: pd.DataFrame, bin_denominator: BinDenominator = "in_out_pkts") -> pd.DataFrame:
    """Return a copy of ``df`` with the 8 engineered ratio columns attached
    (overwriting them if already present). Any M5 code path must call this
    before training/predicting, since Phase 1's raw sample/train/test
    frames do not carry these M5-only columns by default."""
    out = df.copy(deep=True)
    out[ENGINEERED_FEATURES] = compute_ratios(df, bin_denominator=bin_denominator)
    return out
