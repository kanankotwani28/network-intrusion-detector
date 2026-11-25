#!/usr/bin/env python3
"""Phase 2: train M1 (baseline) and M2 (no-timing ablation), evaluate clean
performance, compute M1 feature importance, and run the SHAP-guided M5
feature-selection procedure (frozen once, reused by every later seed).

Requires Phase 1 artifacts (``data/processed/{train,test}.parquet`` and
``artifacts/data/rate_identity_decision.json``) to already exist.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import shap  # noqa: E402

from nids.config.settings import load_settings  # noqa: E402
from nids.evaluation.metrics import (  # noqa: E402
    clean_classification_report,
    confusion_matrix_table,
    summarize_clean_performance,
)
from nids.features.feature_groups import MODEL_FEATURES, STRUCTURAL_FEATURES  # noqa: E402
from nids.models.base import feature_importance_table, fit_model  # noqa: E402
from nids.models.shap_selection import class_capped_subset, select_m5_features  # noqa: E402
from nids.utils.io import read_json, write_csv, write_json  # noqa: E402
from nids.utils.logging import setup_logging  # noqa: E402
from nids.utils.reproducibility import RunRecord, utc_now  # noqa: E402

log = logging.getLogger("run_phase2")

SEED = 42  # Phase 2's own baseline run; the full 5-seed sweep is Phase 5.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/experiment.yaml")
    args = parser.parse_args()

    settings = load_settings(args.config)
    setup_logging(log_file=settings.paths.artifacts_dir / "logs" / "phase2.log")

    train_path = settings.paths.processed_dir / "train.parquet"
    test_path = settings.paths.processed_dir / "test.parquet"
    if not train_path.exists() or not test_path.exists():
        log.error("Phase 1 outputs missing (%s, %s). Run scripts/run_pipeline.py first.", train_path, test_path)
        return 2

    train_df = pd.read_parquet(train_path)
    test_df = pd.read_parquet(test_path)
    log.info("Loaded train=%d test=%d rows", len(train_df), len(test_df))

    params = settings.model.params
    models_dir = settings.paths.artifacts_dir / "models"
    metrics_dir = settings.paths.artifacts_dir / "metrics"
    plots_dir = settings.paths.artifacts_dir / "plots"
    for d in (models_dir, metrics_dir, plots_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ---- M1: standard baseline (all 40 features) ---------------------------
    log.info("Training M1 (baseline, %d features)...", len(MODEL_FEATURES))
    m1 = fit_model("m1", MODEL_FEATURES, train_df, params, seed=SEED)
    m1.save(models_dir / f"m1_seed{SEED}.txt")

    # ---- M2: no-timing ablation (33 structural features) -------------------
    log.info("Training M2 (no-timing ablation, %d features)...", len(STRUCTURAL_FEATURES))
    m2 = fit_model("m2", STRUCTURAL_FEATURES, train_df, params, seed=SEED)
    m2.save(models_dir / f"m2_seed{SEED}.txt")

    clean_rows = []
    class_reports = []
    for model in (m1, m2):
        y_true = test_df["y"].to_numpy()
        y_pred = model.predict(test_df)
        clean_rows.append(summarize_clean_performance(model.name, SEED, y_true, y_pred, settings.experiment.low_support_threshold))
        report = clean_classification_report(y_true, y_pred, settings.experiment.low_support_threshold)
        report.insert(0, "model", model.name)
        class_reports.append(report)
        write_csv(confusion_matrix_table(y_true, y_pred), metrics_dir / "confusion_matrices" / f"{model.name}_seed{SEED}_clean.csv")
        log.info(
            "%s clean: macro_f1=%.4f weighted_f1=%.4f FPR=%.4f attack_recall=%.4f",
            model.name,
            clean_rows[-1]["macro_f1"],
            clean_rows[-1]["weighted_f1"],
            clean_rows[-1]["clean_fpr"],
            clean_rows[-1]["attack_detection_recall"],
        )

    write_csv(pd.DataFrame(clean_rows), metrics_dir / "clean_metrics.csv")
    write_csv(pd.concat(class_reports, ignore_index=True), metrics_dir / "clean_metrics_per_class.csv")

    # ---- M1 feature importance ---------------------------------------------
    importance = feature_importance_table(m1)
    write_csv(importance, metrics_dir / "feature_importance_m1.csv")
    log.info("Top-5 M1 features by gain: %s", importance.head(5)["feature"].tolist())

    # ---- M5 SHAP-guided feature selection (frozen now, reused by all seeds) ---
    exp = settings.experiment
    log.info("Computing SHAP on M1 (class-capped subset, cap=%d/class, seed=%d)...", exp.shap_selection_cap_per_class, SEED)
    result = select_m5_features(
        m1,
        train_df,
        label_col="y",
        threshold=exp.shap_threshold,
        sensitivity_thresholds=exp.shap_sensitivity_thresholds,
        cap_per_class=exp.shap_selection_cap_per_class,
        seed=SEED,
    )
    write_csv(result.importance_table, settings.paths.artifacts_dir / "data" / "shap_selection.csv")
    write_csv(result.sensitivity, settings.paths.artifacts_dir / "data" / "shap_sensitivity.csv")
    write_json(
        settings.paths.artifacts_dir / "data" / "m5_feature_list.json",
        {
            "feature_list": result.feature_list,
            "flagged_fragile_timing_features": result.flagged_fragile,
            "retained_timing_features": result.retained_timing,
            "n_features": len(result.feature_list),
            "threshold": exp.shap_threshold,
            "cap_per_class": exp.shap_selection_cap_per_class,
            "seed": SEED,
            "time_utc": utc_now(),
        },
    )
    log.info("M5 feature list frozen: %d features; flagged fragile: %s", len(result.feature_list), result.flagged_fragile)

    # SHAP summary plot for M1 (shap_summary_m1.png)
    subset = class_capped_subset(train_df, "y", exp.shap_selection_cap_per_class, SEED)
    explainer = shap.TreeExplainer(m1.estimator, model_output="raw")
    shap_values = explainer.shap_values(subset[MODEL_FEATURES])
    plt.figure()
    shap.summary_plot(shap_values, subset[MODEL_FEATURES], show=False, plot_type="bar", class_names=["Benign", "DDoS", "DoS", "Brute-Force"])
    plt.tight_layout()
    plt.savefig(plots_dir / "shap_summary_m1.png", dpi=150)
    plt.close()

    run = RunRecord(settings.run_config_path)
    run.update(
        "phase2",
        {
            "seed": SEED,
            "m1_features": len(MODEL_FEATURES),
            "m2_features": len(STRUCTURAL_FEATURES),
            "m1_clean": clean_rows[0],
            "m2_clean": clean_rows[1],
            "m5_feature_list": result.feature_list,
            "m5_flagged_fragile": result.flagged_fragile,
            "shap_threshold": exp.shap_threshold,
            "time_utc": utc_now(),
        },
    )
    run.mark_phase_complete("phase2_baseline_ablation_shap_selection")
    log.info("Phase 2 complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
