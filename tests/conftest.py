"""Shared pytest fixtures: a small synthetic NetFlow-shaped dataset.

Unit tests never require the real 18.9M-row NF-CSE-CIC-IDS2018-v2 file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nids.features.feature_groups import PUBLISHED_FEATURE_ORDER

RNG = np.random.default_rng(0)


def _base_row(n: int, label: str) -> dict[str, np.ndarray]:
    data = {}
    for col in PUBLISHED_FEATURE_ORDER:
        if col in ("IPV4_SRC_ADDR", "IPV4_DST_ADDR"):
            data[col] = [f"10.0.0.{i % 250}" for i in range(n)]
        elif col == "L4_SRC_PORT":
            data[col] = RNG.integers(1024, 65535, size=n)
        elif col == "L4_DST_PORT":
            data[col] = RNG.choice([80, 443, 22, 21, 53], size=n)
        elif col == "PROTOCOL":
            data[col] = RNG.choice([6, 17], size=n)
        elif col in ("FLOW_DURATION_MILLISECONDS", "DURATION_IN", "DURATION_OUT"):
            data[col] = RNG.integers(1, 20000, size=n).astype(np.int64)
        elif col in ("IN_BYTES", "OUT_BYTES"):
            data[col] = RNG.integers(40, 1_000_000, size=n).astype(np.int64)
        elif col in ("IN_PKTS", "OUT_PKTS"):
            data[col] = RNG.integers(1, 2000, size=n).astype(np.int64)
        elif col in ("SRC_TO_DST_SECOND_BYTES", "DST_TO_SRC_SECOND_BYTES"):
            data[col] = np.zeros(n)
        elif col in ("SRC_TO_DST_AVG_THROUGHPUT", "DST_TO_SRC_AVG_THROUGHPUT"):
            data[col] = np.zeros(n)
        elif col.startswith("NUM_PKTS_"):
            data[col] = RNG.integers(0, 50, size=n).astype(np.int64)
        elif col in ("MIN_TTL", "MAX_TTL", "DNS_TTL_ANSWER"):
            data[col] = RNG.integers(32, 128, size=n).astype(np.int64)
        else:
            data[col] = RNG.integers(0, 10, size=n).astype(np.int64)
    # Fill consistent duration/rate relationships for a fraction of rows.
    dur_s = np.maximum(data["FLOW_DURATION_MILLISECONDS"] / 1000.0, 1e-6)
    data["SRC_TO_DST_SECOND_BYTES"] = data["IN_BYTES"] / dur_s
    data["DST_TO_SRC_SECOND_BYTES"] = data["OUT_BYTES"] / dur_s
    data["SRC_TO_DST_AVG_THROUGHPUT"] = 8 * data["IN_BYTES"] / dur_s
    data["DST_TO_SRC_AVG_THROUGHPUT"] = 8 * data["OUT_BYTES"] / dur_s
    # Packet-size bins sum to IN_PKTS (single-direction convention) for this fixture.
    bins = RNG.integers(0, 20, size=(n, 5)).astype(np.int64)
    in_pkts = bins.sum(axis=1) + 1
    data["IN_PKTS"] = in_pkts
    for i, col in enumerate(
        [
            "NUM_PKTS_UP_TO_128_BYTES",
            "NUM_PKTS_128_TO_256_BYTES",
            "NUM_PKTS_256_TO_512_BYTES",
            "NUM_PKTS_512_TO_1024_BYTES",
            "NUM_PKTS_1024_TO_1514_BYTES",
        ]
    ):
        data[col] = bins[:, i]
    data["Label"] = np.zeros(n, dtype=np.int64) if label == "Benign" else np.ones(n, dtype=np.int64)
    data["Attack"] = [label] * n
    return data


@pytest.fixture
def synthetic_classes() -> dict[str, int]:
    return {
        "Benign": 400,
        "DDOS attack-HOIC": 60,
        "DoS attacks-Hulk": 40,
        "FTP-BruteForce": 20,
        "Bot": 15,  # excluded class, must never appear in output
    }


@pytest.fixture
def synthetic_csv(tmp_path: Path, synthetic_classes: dict[str, int]) -> Path:
    frames = [pd.DataFrame(_base_row(n, label)) for label, n in synthetic_classes.items()]
    df = pd.concat(frames, axis=0, ignore_index=True)
    df = df.sample(frac=1.0, random_state=1).reset_index(drop=True)
    path = tmp_path / "synthetic_nf.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def synthetic_df(synthetic_classes: dict[str, int]) -> pd.DataFrame:
    frames = [pd.DataFrame(_base_row(n, label)) for label, n in synthetic_classes.items()]
    return pd.concat(frames, axis=0, ignore_index=True)
