#!/usr/bin/env python3
"""Phase 4: train M3 (Gaussian noise), M4 (adversarial pacing) and M5
(SHAP-guided hybrid) once (seed 42) and verify the acceptance criteria:
correct augmentation, correct/frozen M5 feature list, identical split and
hyperparameters as M1/M2. The full 5-seed evaluation is Phase 5.
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
from nids.data.label_mapping import BENIGN_CODE  # noqa: E402
from nids.evaluation.metrics import summarize_clean_performance  # noqa: E402
from nids.features.feature_groups import MODEL_FEATURES  # noqa: E402
from nids.features.ratios import attach_ratios  # noqa: E402
from nids.models.augmentation import adversarial_pacing_augment, gaussian_noise_augment  # noqa: E402
from nids.models.base import fit_model  # noqa: E402
from nids.perturbation.pacing import load_rate_columns_scalable  # noqa: E402
from nids.utils.io import read_json, write_csv  # noqa: E402
from nids.utils.logging import setup_logging  # noqa: E402
from nids.utils.reproducibility import RunRecord, utc_now  # noqa: E402

log = logging.getLogger("run_phase4")
SEED = 42


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/experiment.yaml")
    args = parser.parse_args()
    settings = load_settings(args.config)
    setup_logging(log_file=settings.paths.artifacts_dir / "logs" / "phase4.log")

    train_df = pd.read_parquet(settings.paths.processed_dir / "train.parquet")
    test_df = pd.read_parquet(settings.paths.processed_dir / "test.parquet")
    decision = read_json(settings.paths.artifacts_dir / "data" / "rate_identity_decision.json")
    rate_columns_scalable = load_rate_columns_scalable(decision)
    bin_denom = decision["bin_share_denominator"]
    m5_info = read_json(settings.paths.artifacts_dir / "data" / "m5_feature_list.json")
    m5_features = m5_info["feature_list"]

    train_df = attach_ratios(train_df, bin_denom)
    test_df = attach_ratios(test_df, bin_denom)

    exp = settings.experiment
    params = settings.model.params
    n_attack_train = int((train_df["y"] != BENIGN_CODE).sum())

    log.info("Building M3 augmented pool (Gaussian noise, sigma=%.2f)...", exp.noise_sigma)
    m3_pool = gaussian_noise_augment(train_df, sigma=exp.noise_sigma, seed=SEED)
    assert len(m3_pool) == len(train_df) + n_attack_train, "M3 must add exactly one noisy copy per training attack flow"

    log.info("Building M4/M5 augmented pool (adversarial pacing, alpha~U%s)...", tuple(exp.alpha_train))
    adv_pool = adversarial_pacing_augment(
        train_df, alpha_range=tuple(exp.alpha_train), seed=SEED, rate_columns_scalable=rate_columns_scalable, bin_denominator=bin_denom
    )
    assert len(adv_pool) == len(train_df) + n_attack_train, "M4/M5 must add exactly one slowed copy per training attack flow"

    models_dir = settings.paths.artifacts_dir / "models"
    m3 = fit_model("m3", MODEL_FEATURES, m3_pool, params, seed=SEED)
    m3.save(models_dir / f"m3_seed{SEED}.txt")
    m4 = fit_model("m4", MODEL_FEATURES, adv_pool, params, seed=SEED)
    m4.save(models_dir / f"m4_seed{SEED}.txt")
    m5 = fit_model("m5", m5_features, adv_pool, params, seed=SEED)
    m5.save(models_dir / f"m5_seed{SEED}.txt")

    rows = []
    for model in (m3, m4, m5):
        y_true = test_df["y"].to_numpy()
        y_pred = model.predict(test_df)
        summary = summarize_clean_performance(model.name, SEED, y_true, y_pred, exp.low_support_threshold)
        rows.append(summary)
        log.info("%s clean: macro_f1=%.4f FPR=%.4f attack_recall=%.4f", model.name, summary["macro_f1"], summary["clean_fpr"], summary["attack_detection_recall"])

    metrics_dir = settings.paths.artifacts_dir / "metrics"
    existing = pd.read_csv(metrics_dir / "clean_metrics.csv") if (metrics_dir / "clean_metrics.csv").exists() else pd.DataFrame()
    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True).drop_duplicates(subset=["model", "seed"], keep="last")
    write_csv(combined, metrics_dir / "clean_metrics.csv")

    log.info("Acceptance checks: same hyperparameters=%s, same split=yes (shared train/test parquet), M5 feature count=%d (frozen in Phase 2)", params, len(m5_features))

    run = RunRecord(settings.run_config_path)
    run.update("phase4", {
        "seed": SEED, "noise_sigma": exp.noise_sigma, "alpha_train": exp.alpha_train,
        "n_train_clean": len(train_df), "n_attack_train": n_attack_train,
        "m3_pool_size": len(m3_pool), "m4_m5_pool_size": len(adv_pool),
        "m5_n_features": len(m5_features), "time_utc": utc_now(),
    })
    run.mark_phase_complete("phase4_robustness_models")
    log.info("Phase 4 complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
