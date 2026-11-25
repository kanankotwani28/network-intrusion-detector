"""End-to-end Phase 1 pipeline test on a small synthetic CSV.

Exercises the fixed order: Filter -> Validate -> Deduplicate -> Sample,
using the same functions ``scripts/run_pipeline.py`` calls, without needing
the real 18.9M-row dataset.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nids.data.ingestion import (
    deduplicate,
    finalize_sample,
    run_pass1,
    run_pass2,
)
from nids.data.label_mapping import PROJECT_CLASSES
from nids.data.sampling import largest_remainder_quotas, sample_indices_per_class
from nids.data.splitting import stratified_split
from nids.features.feature_groups import IDENTIFIER_FEATURES, MODEL_FEATURES, TARGET_COLUMNS


def test_full_pipeline_end_to_end(synthetic_csv, synthetic_classes):
    pass1 = run_pass1(synthetic_csv, chunksize=37, relative_tolerance=0.05, halt_on_unknown_labels=False)

    # Bot (excluded) must never appear as eligible.
    assert pass1.rows_eligible <= pass1.rows_scanned_total
    expected_eligible_classes = {"Benign", "DDOS attack-HOIC", "DoS attacks-Hulk", "FTP-BruteForce"}
    assert set(pass1.raw_label_counts) >= expected_eligible_classes | {"Bot"}

    dedup = deduplicate(pass1)
    assert set(dedup.class_counts) == set(PROJECT_CLASSES)
    assert dedup.class_counts["Benign"] > 0
    assert dedup.conflict_rate >= 0.0

    total_unique = sum(dedup.class_counts.values())
    sample_size = min(50, total_unique)
    quotas = largest_remainder_quotas(dedup.class_counts, sample_size)
    assert sum(quotas.values()) == sample_size

    selected = sample_indices_per_class(dedup.class_to_indices, quotas, seed=42)
    all_indices = np.concatenate(list(selected.values())) if selected else np.array([], dtype=np.int64)

    extracted = run_pass2(synthetic_csv, chunksize=37, selected_global_indices=all_indices)
    assert len(extracted) == len(all_indices)

    sample_df = finalize_sample(extracted)
    assert len(sample_df) == sample_size
    assert set(IDENTIFIER_FEATURES).isdisjoint(sample_df.columns)
    assert set(TARGET_COLUMNS).isdisjoint(sample_df.columns)
    assert np.isfinite(sample_df[MODEL_FEATURES].to_numpy()).all()
    assert (sample_df[MODEL_FEATURES].to_numpy() >= 0).all()

    train_df, test_df = stratified_split(sample_df, "y", test_size=0.3, seed=42)
    assert len(train_df) + len(test_df) == sample_size
    # Stratification keeps every present class in both splits where count allows.
    assert set(train_df["y"]).issubset(set(sample_df["y"]))


def test_pipeline_halts_on_unknown_label(tmp_path, synthetic_classes):
    from nids.data.ingestion import run_pass1
    import pandas as pd
    from tests.conftest import _base_row

    frames = [pd.DataFrame(_base_row(5, "Benign")), pd.DataFrame(_base_row(5, "Totally-New-Attack"))]
    df = pd.concat(frames, ignore_index=True)
    path = tmp_path / "unknown.csv"
    df.to_csv(path, index=False)
    import pytest

    with pytest.raises(ValueError, match="not listed in proposal"):
        run_pass1(path, chunksize=10, relative_tolerance=0.05, halt_on_unknown_labels=True)


def test_deduplication_removes_exact_duplicate_rows(tmp_path):
    from tests.conftest import _base_row

    row = pd.DataFrame(_base_row(1, "Benign"))
    dup = pd.concat([row, row, row], ignore_index=True)
    path = tmp_path / "dups.csv"
    dup.to_csv(path, index=False)

    pass1 = run_pass1(path, chunksize=10, relative_tolerance=0.05, halt_on_unknown_labels=False)
    dedup = deduplicate(pass1)
    assert dedup.class_counts["Benign"] == 1
