#!/usr/bin/env python3
"""Phase 1 data pipeline: ingest, validate, deduplicate, sample, split.

Usage
-----
    python scripts/run_pipeline.py [--config configs/experiment.yaml]

Requires the raw ``NF-CSE-CIC-IDS2018-v2`` CSV at the path given in the
config (``paths.raw_dataset``). Writes every artifact listed in proposal
Appendix G under "Ingestion, validation, deduplication" and "Sampling and
split", plus ``run_config.json``.

This script performs real execution only: if the raw file is missing it
stops and explains what is needed instead of fabricating output files.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nids.config.settings import Settings, load_settings  # noqa: E402
from nids.data.ingestion import (  # noqa: E402
    deduplicate,
    finalize_sample,
    run_pass1,
    run_pass2,
)
from nids.data.label_mapping import build_label_mapping_log  # noqa: E402
from nids.data.sampling import largest_remainder_quotas, quotas_table, sample_indices_per_class  # noqa: E402
from nids.data.splitting import stratified_split  # noqa: E402
from nids.utils.io import sha256_file, write_csv, write_parquet  # noqa: E402
from nids.utils.logging import setup_logging  # noqa: E402
from nids.utils.reproducibility import RunRecord, utc_now  # noqa: E402

log = logging.getLogger("run_pipeline")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/experiment.yaml")
    args = parser.parse_args()

    settings = load_settings(args.config)
    data_dir = settings.data_reports_dir
    setup_logging(log_file=settings.paths.artifacts_dir / "logs" / "phase1.log")

    raw_path = settings.paths.raw_dataset
    if not raw_path.exists():
        log.error("Raw dataset not found at %s", raw_path)
        print(
            "\nREQUIRED INPUT MISSING\n"
            f"Expected the NF-CSE-CIC-IDS2018-v2 CSV at: {raw_path}\n"
            "Download it from the official UQ dataset page (see proposal reference 3) "
            "and place it at that path, or edit paths.raw_dataset in "
            f"{args.config} to point at your copy.\n"
            "Expected format: CSV, header row matching Appendix A's 43 published "
            "columns plus Label and Attack (45 columns total).\n",
            file=sys.stderr,
        )
        return 2

    run = RunRecord(settings.run_config_path)
    t0 = time.time()

    checksum = None
    if settings.data.compute_checksum:
        log.info("Computing SHA-256 of raw file (one sequential pass)...")
        checksum = sha256_file(raw_path)
        log.info("SHA-256: %s", checksum)

    log.info("Pass 1: scanning %s in chunks of %d", raw_path, settings.data.chunksize)
    pass1 = run_pass1(
        raw_path,
        chunksize=settings.data.chunksize,
        relative_tolerance=settings.identity_checks.relative_tolerance,
        halt_on_unknown_labels=settings.data.halt_on_unknown_labels,
    )
    log.info(
        "Pass 1 done: %d rows scanned, %d eligible (4 project classes), %d valid",
        pass1.rows_scanned_total,
        pass1.rows_eligible,
        pass1.validation.rows_valid,
    )

    # ---- Reports: schema, label mapping, class counts, validation drops ---
    assert pass1.header_report is not None
    write_csv(pass1.header_report, data_dir / "schema_verification.csv")

    label_log = build_label_mapping_log(dict(pass1.raw_label_counts), dict(pass1.binary_label_values))
    write_csv(label_log, data_dir / "label_mapping_log.csv")

    write_csv(pass1.validation.to_frame(["Benign", "DDoS", "DoS", "Brute-Force"]), data_dir / "validation_drops.csv")

    min_pass_rate = settings.identity_checks.min_pass_rate
    identity_decision = pass1.identities.decide(min_pass_rate)
    write_csv(pass1.identities.relation_table(min_pass_rate), data_dir / "rate_identity_checks.csv")
    from nids.utils.io import write_json

    write_json(data_dir / "rate_identity_decision.json", identity_decision)
    log.info("Rate-column scaling decision: %s", identity_decision["rate_columns_scalable"])
    log.info("Packet-size bin denominator: %s", identity_decision["bin_share_denominator"])

    # ---- Deduplication ----------------------------------------------------
    log.info("Deduplicating on hash(features + label)...")
    dedup = deduplicate(pass1)
    write_csv(dedup.conflicts, data_dir / "duplicate_conflicts.csv")
    class_counts_df = pd.DataFrame(
        [{"project_class": c, "unique_count": n} for c, n in dedup.class_counts.items()]
    )
    write_csv(class_counts_df, data_dir / "class_counts.csv")
    log.info("Unique eligible rows per class: %s", dedup.class_counts)
    log.info("Conflict-group rate (of unique rows): %.4f%%", dedup.conflict_rate * 100)

    if dedup.conflict_rate > settings.data.conflict_rate_threshold:
        msg = (
            f"Conflicting-label duplicate groups are {dedup.conflict_rate:.4%} of unique rows, "
            f"above the {settings.data.conflict_rate_threshold:.2%} investigation threshold."
        )
        if settings.data.halt_on_conflict_threshold:
            log.error(msg + " Halting per config (data.halt_on_conflict_threshold=true).")
            run.update(
                "phase1_halted",
                {"reason": "conflict_rate_threshold_exceeded", "conflict_rate": dedup.conflict_rate, "time_utc": utc_now()},
            )
            return 3
        log.warning(msg + " Continuing (data.halt_on_conflict_threshold=false).")

    total_unique = sum(dedup.class_counts.values())
    sample_size = settings.data.sample_size
    if total_unique < sample_size:
        log.error(
            "Only %d unique eligible flows available across all 4 classes; cannot sample %d without duplication.",
            total_unique,
            sample_size,
        )
        run.update(
            "phase1_halted",
            {"reason": "insufficient_unique_rows", "available": total_unique, "requested": sample_size, "time_utc": utc_now()},
        )
        return 4

    quotas = largest_remainder_quotas(dedup.class_counts, sample_size)
    write_csv(quotas_table(dedup.class_counts, quotas, sample_size), data_dir / "sampling_quotas.csv")
    log.info("Sampling quotas: %s", quotas)

    selected = sample_indices_per_class(dedup.class_to_indices, quotas, seed=settings.data.sampling_seed)
    all_indices = np.concatenate([v for v in selected.values() if len(v)])

    log.info("Pass 2: extracting %d selected rows from %s", len(all_indices), raw_path)
    extracted = run_pass2(raw_path, chunksize=settings.data.chunksize, selected_global_indices=all_indices)

    sample_df = finalize_sample(extracted)
    assert len(sample_df) == sample_size, f"expected {sample_size} sampled rows, got {len(sample_df)}"
    assert np.isfinite(sample_df.drop(columns=["project_class"]).select_dtypes("number").to_numpy()).all()

    processed_dir = settings.paths.processed_dir
    write_parquet(sample_df, processed_dir / "sample_100k.parquet")

    log.info("Splitting 70/30 stratified (seed=%d)", settings.data.split_seed)
    train_df, test_df = stratified_split(sample_df, "y", test_size=settings.data.test_size, seed=settings.data.split_seed)
    write_parquet(train_df, processed_dir / "train.parquet")
    write_parquet(test_df, processed_dir / "test.parquet")
    log.info("Train: %d rows, Test: %d rows", len(train_df), len(test_df))

    elapsed = time.time() - t0
    run.update(
        "phase1",
        {
            "raw_dataset_path": str(raw_path),
            "raw_dataset_sha256": checksum,
            "rows_scanned": pass1.rows_scanned_total,
            "rows_eligible_four_classes": pass1.rows_eligible,
            "rows_valid": pass1.validation.rows_valid,
            "unknown_labels_found": sorted(pass1.unknown_labels),
            "unique_class_counts": dedup.class_counts,
            "conflict_rate": dedup.conflict_rate,
            "sample_size": sample_size,
            "sampling_quotas": quotas,
            "sampling_seed": settings.data.sampling_seed,
            "split_seed": settings.data.split_seed,
            "test_size": settings.data.test_size,
            "train_rows": len(train_df),
            "test_rows": len(test_df),
            "rate_identity_decision": identity_decision,
            "chunksize": settings.data.chunksize,
            "elapsed_seconds": elapsed,
            "time_utc": utc_now(),
        },
    )
    run.mark_phase_complete("phase1_data_pipeline")
    log.info("Phase 1 complete in %.1fs. Artifacts written under %s and %s", elapsed, data_dir, processed_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
