#!/usr/bin/env python3
"""Phase 3: consistency-preserving perturbation engine, run across all 5
seeds (moderate alpha~U(1.5,2.5) and OOD alpha~U(3.0,4.5)), with full
algebraic consistency verification, plus an M1/M2 evasion sanity check.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd  # noqa: E402

from nids.config.settings import load_settings  # noqa: E402
from nids.evaluation.attack_evasion import aer_by_class  # noqa: E402
from nids.features.feature_groups import MODEL_FEATURES, STRUCTURAL_FEATURES  # noqa: E402
from nids.models.base import fit_model  # noqa: E402
from nids.perturbation.consistency import verify_perturbation  # noqa: E402
from nids.perturbation.pacing import load_rate_columns_scalable, perturb_attack_flows  # noqa: E402
from nids.utils.io import read_json, write_csv, write_parquet  # noqa: E402
from nids.utils.logging import setup_logging  # noqa: E402
from nids.utils.reproducibility import RunRecord, utc_now  # noqa: E402

log = logging.getLogger("run_phase3")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/experiment.yaml")
    args = parser.parse_args()

    settings = load_settings(args.config)
    setup_logging(log_file=settings.paths.artifacts_dir / "logs" / "phase3.log")

    train_df = pd.read_parquet(settings.paths.processed_dir / "train.parquet")
    test_df = pd.read_parquet(settings.paths.processed_dir / "test.parquet")

    decision = read_json(settings.paths.artifacts_dir / "data" / "rate_identity_decision.json")
    rate_columns_scalable = load_rate_columns_scalable(decision)
    bin_denominator = decision["bin_share_denominator"]
    log.info("Rate columns scalable: %s | bin denominator: %s", rate_columns_scalable, bin_denominator)

    exp = settings.experiment
    perturbed_dir = settings.paths.processed_dir
    consistency_rows = []
    aer_rows = []

    for seed in exp.seeds:
        for regime, alpha_range in (("moderate", exp.alpha_moderate), ("ood", exp.alpha_ood)):
            result = perturb_attack_flows(
                test_df, alpha_range=tuple(alpha_range), seed=seed,
                rate_columns_scalable=rate_columns_scalable, bin_denominator=bin_denominator,
            )
            write_parquet(result.perturbed, perturbed_dir / f"perturbed_{regime}_seed{seed}.parquet")

            report = verify_perturbation(
                test_df, result, rate_columns_scalable, settings.identity_checks.relative_tolerance,
                settings.identity_checks.min_pass_rate,
            )
            report.insert(0, "seed", seed)
            report.insert(1, "regime", regime)
            consistency_rows.append(report)
            n_fail = int((~report["passed"]).sum())
            if n_fail:
                log.error("seed=%d regime=%s: %d consistency checks FAILED:\n%s", seed, regime, n_fail, report[~report["passed"]])
            else:
                log.info("seed=%d regime=%s: all %d consistency checks passed", seed, regime, len(report))

        # M1/M2 evasion sanity check (full 5-model x 5-seed evaluation is Phase 5).
        for name, feats in (("m1", MODEL_FEATURES), ("m2", STRUCTURAL_FEATURES)):
            model = fit_model(name, feats, train_df, settings.model.params, seed=seed)
            y_true = test_df["y"].to_numpy()
            y_pred_clean = model.predict(test_df)
            for regime in ("moderate", "ood"):
                perturbed = pd.read_parquet(perturbed_dir / f"perturbed_{regime}_seed{seed}.parquet")
                y_pred_pert = model.predict(perturbed)
                table = aer_by_class(y_true, y_pred_clean, y_pred_pert, low_support_threshold=exp.low_support_threshold)
                table.insert(0, "seed", seed)
                table.insert(1, "model", name)
                table.insert(2, "regime", regime)
                aer_rows.append(table)
                overall = table[table["class"] == "overall"].iloc[0]
                log.info("seed=%d %s %s: AER=%.2f%% (n=%d)", seed, name, regime, overall["aer"], overall["n_detected_clean"])

    write_csv(pd.concat(consistency_rows, ignore_index=True), settings.paths.artifacts_dir / "data" / "perturbation_consistency_check.csv")
    write_csv(pd.concat(aer_rows, ignore_index=True), settings.paths.artifacts_dir / "metrics" / "aer_m1_m2_by_seed.csv")

    run = RunRecord(settings.run_config_path)
    run.update("phase3", {"seeds": exp.seeds, "rate_columns_scalable": rate_columns_scalable, "bin_denominator": bin_denominator, "time_utc": utc_now()})
    run.mark_phase_complete("phase3_perturbation_engine")
    log.info("Phase 3 complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
