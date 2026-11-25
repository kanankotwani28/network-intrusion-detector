"""Empirical data-identity checks on clean data (proposal Appendix C).

The pacing perturbation multiplies durations by alpha and divides rate /
throughput columns by alpha. That is only physically consistent if, in the
clean data, ``rate ~ factor * bytes / duration``. These checks measure the
relationship empirically instead of assuming it.

For each rate column we test several *candidate* relations (which byte
column, which duration column, bytes/s vs bits/s). A rate column is approved
for 1/alpha scaling only if its best *proportional* candidate holds within
``relative_tolerance`` for at least ``min_pass_rate`` of positive-duration
flows. A floored-seconds candidate is also measured as a diagnostic only: it
is not proportional to 1/duration, so it cannot justify 1/alpha scaling.

The module also determines whether the five packet-size bins count packets
in one direction (``IN_PKTS``) or both (``IN_PKTS + OUT_PKTS``), which fixes
the denominator of the engineered packet-size shares.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nids.features.feature_groups import PACKET_SIZE_BIN_FEATURES


@dataclass(frozen=True)
class RateCandidate:
    rate_column: str
    bytes_column: str
    duration_column: str
    factor: float  # 1 for bytes/s, 8 for bits/s
    duration_mode: str = "continuous"  # or "floor_seconds_min1" (diagnostic)

    @property
    def name(self) -> str:
        unit = "bytes/s" if self.factor == 1 else "bits/s"
        return f"{self.rate_column} ~ {self.factor:g}*{self.bytes_column}/{self.duration_column}[{self.duration_mode}] ({unit})"

    @property
    def proportional(self) -> bool:
        return self.duration_mode == "continuous"

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        dur_ms = df[self.duration_column].to_numpy(dtype=np.float64)
        if self.duration_mode == "continuous":
            dur_s = dur_ms / 1000.0
        else:
            dur_s = np.maximum(np.floor(dur_ms / 1000.0), 1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            return self.factor * df[self.bytes_column].to_numpy(dtype=np.float64) / dur_s


def default_candidates() -> list[RateCandidate]:
    pairs = {
        "SRC_TO_DST_SECOND_BYTES": ("IN_BYTES", ["FLOW_DURATION_MILLISECONDS", "DURATION_IN"], [1.0, 8.0]),
        "DST_TO_SRC_SECOND_BYTES": ("OUT_BYTES", ["FLOW_DURATION_MILLISECONDS", "DURATION_OUT"], [1.0, 8.0]),
        "SRC_TO_DST_AVG_THROUGHPUT": ("IN_BYTES", ["FLOW_DURATION_MILLISECONDS", "DURATION_IN"], [8.0, 1.0]),
        "DST_TO_SRC_AVG_THROUGHPUT": ("OUT_BYTES", ["FLOW_DURATION_MILLISECONDS", "DURATION_OUT"], [8.0, 1.0]),
    }
    out: list[RateCandidate] = []
    for rate, (byte_col, durs, factors) in pairs.items():
        for dur in durs:
            for f in factors:
                out.append(RateCandidate(rate, byte_col, dur, f, "continuous"))
                out.append(RateCandidate(rate, byte_col, dur, f, "floor_seconds_min1"))
    return out


@dataclass
class IdentityAccumulator:
    """Streams relation statistics over chunks of valid clean rows."""

    relative_tolerance: float = 0.05
    candidates: list[RateCandidate] = field(default_factory=default_candidates)
    n_positive: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    n_pass: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    bin_rows: int = 0
    bin_matches: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def update(self, df: pd.DataFrame) -> None:
        for cand in self.candidates:
            dur = df[cand.duration_column].to_numpy(dtype=np.float64)
            pos = dur > 0
            if not pos.any():
                continue
            sub = df.loc[pos]
            pred = cand.predict(sub)
            obs = sub[cand.rate_column].to_numpy(dtype=np.float64)
            self.n_positive[cand.name] += int(pos.sum())
            self.n_pass[cand.name] += int(relation_holds(obs, pred, self.relative_tolerance).sum())

        bins = df[PACKET_SIZE_BIN_FEATURES].to_numpy(dtype=np.float64).sum(axis=1)
        in_p = df["IN_PKTS"].to_numpy(dtype=np.float64)
        out_p = df["OUT_PKTS"].to_numpy(dtype=np.float64)
        self.bin_rows += len(df)
        self.bin_matches["in_pkts"] += int(np.sum(bins == in_p))
        self.bin_matches["out_pkts"] += int(np.sum(bins == out_p))
        self.bin_matches["in_out_pkts"] += int(np.sum(bins == in_p + out_p))

    # ------------------------------------------------------------------
    def relation_table(self, min_pass_rate: float) -> pd.DataFrame:
        rows = []
        for cand in self.candidates:
            n = self.n_positive.get(cand.name, 0)
            k = self.n_pass.get(cand.name, 0)
            rate = k / n if n else float("nan")
            rows.append(
                {
                    "rate_column": cand.rate_column,
                    "bytes_column": cand.bytes_column,
                    "duration_column": cand.duration_column,
                    "factor": cand.factor,
                    "duration_mode": cand.duration_mode,
                    "proportional_to_1_over_duration": cand.proportional,
                    "n_positive_duration": n,
                    "n_within_tolerance": k,
                    "pass_rate": rate,
                    "meets_acceptance": bool(cand.proportional and n > 0 and rate >= min_pass_rate),
                }
            )
        return pd.DataFrame(rows)

    def decide(self, min_pass_rate: float) -> dict[str, object]:
        """Return the scaling decision per rate column and the bin denominator."""
        table = self.relation_table(min_pass_rate)
        decisions: dict[str, dict[str, object]] = {}
        for rate_col, grp in table.groupby("rate_column", sort=False):
            prop = grp[grp["proportional_to_1_over_duration"]].sort_values("pass_rate", ascending=False)
            best = prop.iloc[0]
            decisions[str(rate_col)] = {
                "scale_by_inverse_alpha": bool(best["meets_acceptance"]),
                "best_relation": f"{best['factor']:g}*{best['bytes_column']}/{best['duration_column']}",
                "best_pass_rate": None if pd.isna(best["pass_rate"]) else float(best["pass_rate"]),
                "n_positive_duration": int(best["n_positive_duration"]),
            }
        match_rates = {k: (v / self.bin_rows if self.bin_rows else float("nan")) for k, v in self.bin_matches.items()}
        best_bin = max(("in_pkts", "in_out_pkts"), key=lambda k: match_rates.get(k, 0.0))
        return {
            "rate_columns": decisions,
            "rate_columns_scalable": [c for c, d in decisions.items() if d["scale_by_inverse_alpha"]],
            "rate_columns_failed": [c for c, d in decisions.items() if not d["scale_by_inverse_alpha"]],
            "packet_bin_sum_match_rates": match_rates,
            "packet_bin_rows_checked": self.bin_rows,
            "bin_share_denominator": best_bin,
            "relative_tolerance": self.relative_tolerance,
            "min_pass_rate": min_pass_rate,
        }


def relation_holds(observed: np.ndarray, predicted: np.ndarray, tol: float) -> np.ndarray:
    """Element-wise ``|obs - pred| <= tol * |pred|``; ``pred == 0`` needs ``obs == 0``."""
    observed = np.asarray(observed, dtype=np.float64)
    predicted = np.asarray(predicted, dtype=np.float64)
    out = np.zeros(observed.shape, dtype=bool)
    finite = np.isfinite(predicted) & np.isfinite(observed)
    zero = finite & (predicted == 0)
    out[zero] = observed[zero] == 0
    nz = finite & (predicted != 0)
    out[nz] = np.abs(observed[nz] - predicted[nz]) <= tol * np.abs(predicted[nz])
    return out
