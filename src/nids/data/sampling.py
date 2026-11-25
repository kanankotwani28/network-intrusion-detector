"""Largest-remainder quota computation and seeded per-class sampling."""

from __future__ import annotations

import numpy as np
import pandas as pd


def largest_remainder_quotas(class_counts: dict[str, int], total: int) -> dict[str, int]:
    """Proportional quotas that sum exactly to ``total`` (Section 7.1 step 3).

    ``quota_c = total * count_c / sum(counts)``, rounded down, then the
    remaining units distributed one each to the classes with the largest
    fractional remainder.
    """
    classes = list(class_counts)
    counts = np.array([class_counts[c] for c in classes], dtype=np.float64)
    grand_total = counts.sum()
    if grand_total <= 0:
        raise ValueError("Cannot compute quotas from zero eligible rows")
    exact = total * counts / grand_total
    floor = np.floor(exact).astype(np.int64)
    remainder = exact - floor
    deficit = int(total - floor.sum())
    if deficit > 0:
        order = np.argsort(-remainder, kind="stable")
        for idx in order[:deficit]:
            floor[idx] += 1
    quotas = {c: int(q) for c, q in zip(classes, floor)}
    assert sum(quotas.values()) == total, "largest-remainder quotas must sum exactly to total"
    return quotas


def sample_indices_per_class(
    class_to_indices: dict[str, np.ndarray], quotas: dict[str, int], seed: int
) -> dict[str, np.ndarray]:
    """Draw ``quotas[c]`` indices uniformly without replacement from each class."""
    rng = np.random.default_rng(seed)
    out: dict[str, np.ndarray] = {}
    for cls, idx in class_to_indices.items():
        n = quotas[cls]
        if n > len(idx):
            raise ValueError(f"Class {cls!r} has only {len(idx)} unique eligible rows, needs {n}")
        chosen = rng.choice(idx, size=n, replace=False)
        out[cls] = np.sort(chosen)
    return out


def quotas_table(
    class_counts: dict[str, int], quotas: dict[str, int], total_sample: int
) -> pd.DataFrame:
    rows = []
    grand_total = sum(class_counts.values())
    for cls in class_counts:
        rows.append(
            {
                "project_class": cls,
                "unique_eligible_count": class_counts[cls],
                "share_of_unique": class_counts[cls] / grand_total if grand_total else 0.0,
                "quota": quotas[cls],
                "share_of_sample": quotas[cls] / total_sample if total_sample else 0.0,
            }
        )
    return pd.DataFrame(rows)
