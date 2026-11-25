"""Two-pass, memory-safe ingestion pipeline (proposal Section 7.1).

Pass 1 (scan): read the raw CSV in chunks, filter to the four project
classes, validate, drop identifiers, hash every valid row, and accumulate
compact metadata (hash, class code, global row index) plus statistics. The
full raw dataset is never held in memory — only ``O(eligible rows)`` arrays
of a few bytes each.

Deduplication and stratified sampling then run purely on that metadata.

Pass 2 (extract): re-read the file in chunks and keep only the rows whose
global index was selected, writing the final sample to Parquet.

Order is fixed and enforced by this module's call sequence: Filter ->
Validate -> Deduplicate -> Sample -> (caller does) Split.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from nids.data.deduplication import row_hashes, verify_hash_collisions
from nids.data.identities import IdentityAccumulator
from nids.data.label_mapping import (
    ATTACK_CODES,
    BENIGN_CODE,
    PROJECT_CLASSES,
    map_attack_labels,
)
from nids.data.sampling import largest_remainder_quotas, sample_indices_per_class
from nids.data.schema import verify_header
from nids.data.validation import ValidationStats, validate_chunk
from nids.features.feature_groups import (
    ATTACK_COLUMN,
    IDENTIFIER_FEATURES,
    LABEL_COLUMN,
    MODEL_FEATURES,
    PUBLISHED_COLUMNS,
)

log = logging.getLogger(__name__)


@dataclass
class ConflictGroup:
    """One (features, differing labels) group found during deduplication."""

    hash_value: int
    labels: tuple[int, ...]
    count: int


@dataclass
class Pass1Result:
    # hash -> first global index seen with that hash (kept copy candidate)
    kept_index_by_hash: dict[int, int] = field(default_factory=dict)
    kept_label_by_hash: dict[int, int] = field(default_factory=dict)
    # hash -> set of (label, first_index) seen, for conflict detection
    hash_labels: dict[int, set[int]] = field(default_factory=lambda: defaultdict(set))
    hash_label_first_index: dict[tuple[int, int], int] = field(default_factory=dict)
    raw_label_counts: Counter = field(default_factory=Counter)
    binary_label_values: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    rows_scanned_total: int = 0
    rows_eligible: int = 0
    validation: ValidationStats = field(default_factory=ValidationStats)
    identities: IdentityAccumulator = field(default_factory=IdentityAccumulator)
    header_report: pd.DataFrame | None = None
    unknown_labels: set[str] = field(default_factory=set)


def _read_chunks(data_path: Path, chunksize: int, usecols: list[str] | None = None) -> Iterator[pd.DataFrame]:
    """Stream a dataset file in row chunks, regardless of on-disk format.

    Supports CSV (``pandas.read_csv(chunksize=...)``) and Parquet. A Parquet
    file need not contain multiple row groups to be read memory-safely:
    :meth:`pyarrow.parquet.ParquetFile.iter_batches` decodes a row group
    incrementally in ``batch_size``-row slices, so even the single
    641MB/17M-row file this project uses is never materialised whole.
    """
    suffix = data_path.suffix.lower()
    if suffix == ".parquet":
        import pyarrow.parquet as pq

        pf = pq.ParquetFile(data_path)
        for batch in pf.iter_batches(batch_size=chunksize, columns=usecols):
            yield batch.to_pandas()
    elif suffix in (".csv", ".txt", ""):
        reader = pd.read_csv(data_path, chunksize=chunksize, usecols=usecols, low_memory=False)
        yield from reader
    else:
        raise ValueError(f"Unsupported dataset file format: {suffix!r} ({data_path})")


def run_pass1(
    csv_path: Path,
    chunksize: int,
    relative_tolerance: float,
    halt_on_unknown_labels: bool = True,
) -> Pass1Result:
    """Scan the raw file once; return compact metadata and statistics."""
    result = Pass1Result()
    global_index = 0

    first_chunk = True
    for chunk in _read_chunks(csv_path, chunksize):
        if first_chunk:
            result.header_report = verify_header(list(chunk.columns), chunk)
            missing_optional = [c for c in PUBLISHED_COLUMNS if c not in chunk.columns]
            if missing_optional:
                log.warning("Columns absent from file (treated as absent features): %s", missing_optional)
            first_chunk = False

        n = len(chunk)
        result.rows_scanned_total += n

        raw_attack = chunk[ATTACK_COLUMN].astype(str)
        for lbl, cnt in raw_attack.value_counts().items():
            result.raw_label_counts[lbl] += int(cnt)
        if LABEL_COLUMN in chunk.columns:
            for lbl, bin_val in zip(raw_attack, chunk[LABEL_COLUMN]):
                result.binary_label_values[lbl].add(bin_val)

        codes_all = map_attack_labels(raw_attack)
        unknown_mask = (codes_all == -1) & ~raw_attack.isin(_excluded_labels())
        if unknown_mask.any():
            result.unknown_labels.update(raw_attack[unknown_mask].unique().tolist())

        eligible_mask = codes_all != -1
        eligible_idx_local = np.flatnonzero(eligible_mask)
        if len(eligible_idx_local) == 0:
            global_index += n
            continue

        eligible_chunk = chunk.iloc[eligible_idx_local]
        eligible_codes = codes_all[eligible_idx_local]
        global_indices = global_index + eligible_idx_local

        present_model_cols = [c for c in MODEL_FEATURES if c in eligible_chunk.columns]
        if len(present_model_cols) != len(MODEL_FEATURES):
            missing = set(MODEL_FEATURES) - set(present_model_cols)
            raise ValueError(f"Required model feature columns missing from file: {sorted(missing)}")

        features, valid_mask, chunk_stats = validate_chunk(eligible_chunk[MODEL_FEATURES], eligible_codes)
        result.validation.merge_chunk(chunk_stats)
        result.rows_eligible += int(valid_mask.sum())

        v_features = features.loc[valid_mask]
        v_codes = eligible_codes[valid_mask]
        v_global_idx = global_indices[valid_mask]

        if len(v_features) > 0:
            result.identities.update(
                pd.concat([v_features.reset_index(drop=True)], axis=1)
            )
            hashes = row_hashes(v_features.reset_index(drop=True), v_codes)
            for h, lbl, gidx in zip(hashes, v_codes, v_global_idx):
                h_int = int(h)
                result.hash_labels[h_int].add(int(lbl))
                key = (h_int, int(lbl))
                if key not in result.hash_label_first_index:
                    result.hash_label_first_index[key] = int(gidx)

        global_index += n

    if halt_on_unknown_labels and result.unknown_labels:
        raise ValueError(
            "Dataset contains Attack labels not listed in proposal Appendix B: "
            f"{sorted(result.unknown_labels)}. Refusing to silently map them."
        )

    return result


def _excluded_labels() -> set[str]:
    from nids.data.label_mapping import EXCLUDED_LABELS

    return set(EXCLUDED_LABELS)


@dataclass
class DeduplicationResult:
    # project_class -> np.ndarray of selected (unique, de-conflicted) global indices
    class_to_indices: dict[str, np.ndarray]
    class_counts: dict[str, int]
    conflicts: pd.DataFrame
    conflict_rate: float


def deduplicate(pass1: Pass1Result) -> DeduplicationResult:
    """Resolve Pass 1's hash->label map into one kept index per (hash,label).

    Same features + same label: keep first occurrence (handled naturally,
    since Pass 1 recorded the first global index per (hash,label) key).
    Same features + conflicting labels: keep one copy per distinct pair and
    log the conflict; nothing is silently dropped.
    """
    conflict_rows = []
    n_conflicting_groups = 0
    class_to_indices: dict[str, list[int]] = {c: [] for c in PROJECT_CLASSES}

    for h, labels in pass1.hash_labels.items():
        if len(labels) > 1:
            n_conflicting_groups += 1
            conflict_rows.append(
                {
                    "hash": h,
                    "labels": ";".join(PROJECT_CLASSES[l] for l in sorted(labels)),
                    "n_distinct_labels": len(labels),
                }
            )
        for lbl in labels:
            idx = pass1.hash_label_first_index[(h, lbl)]
            class_to_indices[PROJECT_CLASSES[lbl]].append(idx)

    total_unique = sum(len(v) for v in class_to_indices.values())
    conflict_rate = n_conflicting_groups / total_unique if total_unique else 0.0

    class_counts = {c: len(v) for c, v in class_to_indices.items()}
    conflicts_df = pd.DataFrame(conflict_rows, columns=["hash", "labels", "n_distinct_labels"])
    return DeduplicationResult(
        class_to_indices={c: np.array(sorted(v), dtype=np.int64) for c, v in class_to_indices.items()},
        class_counts=class_counts,
        conflicts=conflicts_df,
        conflict_rate=conflict_rate,
    )


def run_pass2(
    csv_path: Path,
    chunksize: int,
    selected_global_indices: np.ndarray,
) -> pd.DataFrame:
    """Re-read the file, keeping only rows whose global index was selected."""
    wanted = np.sort(selected_global_indices)
    frames = []
    global_index = 0
    wanted_set = set(wanted.tolist())
    for chunk in _read_chunks(csv_path, chunksize):
        n = len(chunk)
        local_idx = [i for i in range(n) if (global_index + i) in wanted_set]
        if local_idx:
            frames.append(chunk.iloc[local_idx].copy())
        global_index += n
    if not frames:
        return pd.DataFrame(columns=PUBLISHED_COLUMNS)
    out = pd.concat(frames, axis=0, ignore_index=True)
    return out


def finalize_sample(raw_rows: pd.DataFrame) -> pd.DataFrame:
    """Drop identifiers, map labels, coerce features -> the 100k sample frame."""
    codes = map_attack_labels(raw_rows[ATTACK_COLUMN].astype(str))
    from nids.data.validation import coerce_features

    features, _ = coerce_features(raw_rows[MODEL_FEATURES])
    out = features.copy()
    out["project_class"] = [PROJECT_CLASSES[c] for c in codes]
    out["y"] = codes.astype(np.int8)
    return out.reset_index(drop=True)
