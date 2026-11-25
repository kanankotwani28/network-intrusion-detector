"""Parquet is the format the real NF-CSE-CIC-IDS2018-v2 mirror ships in
(Kaggle dhoogla release has no IP-address columns and is a single row
group), so the chunked reader and Pass 1 must both support it.
"""

from __future__ import annotations

import pandas as pd

from nids.data.ingestion import run_pass1
from nids.features.feature_groups import IDENTIFIER_FEATURES


def test_pass1_reads_parquet_without_identifier_columns(tmp_path, synthetic_df):
    # Simulate the real mirror: no IPV4_SRC_ADDR / IPV4_DST_ADDR columns.
    df = synthetic_df.drop(columns=["IPV4_SRC_ADDR", "IPV4_DST_ADDR"])
    path = tmp_path / "mini.parquet"
    df.to_parquet(path, index=False)

    result = run_pass1(path, chunksize=37, relative_tolerance=0.05, halt_on_unknown_labels=False)
    assert result.rows_scanned_total == len(df)
    assert result.rows_eligible > 0
    assert not result.unknown_labels


def test_parquet_chunking_matches_csv_chunking(tmp_path, synthetic_df):
    parquet_path = tmp_path / "a.parquet"
    csv_path = tmp_path / "a.csv"
    synthetic_df.to_parquet(parquet_path, index=False)
    synthetic_df.to_csv(csv_path, index=False)

    r1 = run_pass1(parquet_path, chunksize=41, relative_tolerance=0.05, halt_on_unknown_labels=False)
    r2 = run_pass1(csv_path, chunksize=41, relative_tolerance=0.05, halt_on_unknown_labels=False)
    assert r1.rows_scanned_total == r2.rows_scanned_total
    assert r1.rows_eligible == r2.rows_eligible
    assert dict(r1.raw_label_counts) == dict(r2.raw_label_counts)
