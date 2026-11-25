#!/usr/bin/env python3
"""Phase 5: full 5-seed evaluation of M1-M5 (clean/moderate/OOD), AER,
post-perturbation recall, mean+/-std aggregation, comparison plots, and
the non-circular SHAP attribution-drift audit (M1 vs M4 vs M5, OOD, seed
42). Each seed retrains all five models from scratch on the same fixed
split, per the proposal's five-seed protocol.
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
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nids.config.settings import load_settings  # noqa: E402
from nids.data.label_mapping import BENIGN_CODE, PROJECT_CLASSES  # noqa: E402
from nids.evaluation.aggregation import aggregate_over_seeds  # noqa: E402
from nids.evaluation.attack_evasion import aer_by_class  # noqa: E402
from nids.evaluation.metrics import confusion_matrix_table, summarize_clean_performance  # noqa: E402
from nids.explainability.shap_drift import audit_attribution_drift, build_audit_sample, group_summary  # noqa: E402
from nids.features.feature_groups import MODEL_FEATURES, STRUCTURAL_FEATURES  # noqa: E402
from nids.features.ratios import attach_ratios  # noqa: E402
from nids.models.augmentation import adversarial_pacing_augment, gaussian_noise_augment  # noqa: E402
from nids.models.base import fit_model  # noqa: E402
from nids.perturbation.pacing import load_rate_columns_scalable  # noqa: E402
from nids.utils.io import read_json, write_csv  # noqa: E402
from nids.utils.logging import setup_logging  # noqa: E402
from nids.utils.reproducibility import RunRecord, utc_now  # noqa: E402

log = logging.getLogger("run_phase5")


def train_all_models(train_df, m5_features, params, seed, exp, rate_columns_scalable, bin_denom):
    models = {}
    models["m1"] = fit_model("m1", MODEL_FEATURES, train_df, params, seed=seed)
    models["m2"] = fit_model("m2", STRUCTURAL_FEATURES, train_df, params, seed=seed)
    m3_pool = gaussian_noise_augment(train_df, sigma=exp.noise_sigma, seed=seed)
    models["m3"] = fit_model("m3", MODEL_FEATURES, m3_pool, params, seed=seed)
    adv_pool = adversarial_pacing_augment(
        train_df, alpha_range=tuple(exp.alpha_train), seed=seed,
        rate_columns_scalable=rate_columns_scalable, bin_denominator=bin_denom,
    )
    models["m4"] = fit_model("m4", MODEL_FEATURES, adv_pool, params, seed=seed)
    models["m5"] = fit_model("m5", m5_features, adv_pool, params, seed=seed)
    return models


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/experiment.yaml")
    args = parser.parse_args()
    settings = load_settings(args.config)
    setup_logging(log_file=settings.paths.artifacts_dir / "logs" / "phase5.log")

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
    y_true = test_df["y"].to_numpy()

    metrics_dir = settings.paths.artifacts_dir / "metrics"
    cm_dir = metrics_dir / "confusion_matrices"
    plots_dir = settings.paths.artifacts_dir / "plots" / "comparison_charts"
    for d in (metrics_dir, cm_dir, plots_dir):
        d.mkdir(parents=True, exist_ok=True)

    clean_rows, moderate_rows, ood_rows, aer_rows = [], [], [], []
    seed42_models = None  # kept for the SHAP audit

    for seed in exp.seeds:
        log.info("=== seed %d: training all 5 models ===", seed)
        models = train_all_models(train_df, m5_features, params, seed, exp, rate_columns_scalable, bin_denom)
        if seed == 42:
            seed42_models = models

        moderate_test = attach_ratios(pd.read_parquet(settings.paths.processed_dir / f"perturbed_moderate_seed{seed}.parquet"), bin_denom)
        ood_test = attach_ratios(pd.read_parquet(settings.paths.processed_dir / f"perturbed_ood_seed{seed}.parquet"), bin_denom)
        flow_ms = test_df["FLOW_DURATION_MILLISECONDS"].to_numpy()
        is_zero_duration = (y_true != BENIGN_CODE) & (flow_ms == 0)

        for name, model in models.items():
            model.save(settings.paths.artifacts_dir / "models" / f"{name}_seed{seed}.txt")
            y_pred_clean = model.predict(test_df)
            y_pred_mod = model.predict(moderate_test)
            y_pred_ood = model.predict(ood_test)

            clean_rows.append(summarize_clean_performance(name, seed, y_true, y_pred_clean, exp.low_support_threshold))
            moderate_rows.append({"model": name, "seed": seed, **summarize_clean_performance(name, seed, y_true, y_pred_mod, exp.low_support_threshold)})
            ood_rows.append({"model": name, "seed": seed, **summarize_clean_performance(name, seed, y_true, y_pred_ood, exp.low_support_threshold)})

            for regime, y_pred_pert in (("moderate", y_pred_mod), ("ood", y_pred_ood)):
                table = aer_by_class(y_true, y_pred_clean, y_pred_pert, is_zero_duration, exp.low_support_threshold)
                table.insert(0, "seed", seed)
                table.insert(1, "model", name)
                table.insert(2, "regime", regime)
                aer_rows.append(table)

            if seed == 42:
                write_csv(confusion_matrix_table(y_true, y_pred_clean), cm_dir / f"{name}_seed42_clean.csv")
                write_csv(confusion_matrix_table(y_true, y_pred_ood), cm_dir / f"{name}_seed42_ood.csv")

        log.info("seed %d done", seed)

    clean_df = pd.DataFrame(clean_rows)
    moderate_df = pd.DataFrame(moderate_rows)
    ood_df = pd.DataFrame(ood_rows)
    aer_df = pd.concat(aer_rows, ignore_index=True)

    write_csv(clean_df, metrics_dir / "clean_metrics_all_seeds.csv")
    write_csv(moderate_df, metrics_dir / "metrics_moderate.csv")
    write_csv(ood_df, metrics_dir / "metrics_ood.csv")
    write_csv(aer_df, metrics_dir / "aer_by_class.csv")

    value_cols = ["macro_f1", "weighted_f1", "clean_fpr", "attack_detection_recall"]
    write_csv(aggregate_over_seeds(clean_df, ["model"], value_cols), metrics_dir / "clean_metrics_summary.csv")
    write_csv(aggregate_over_seeds(moderate_df, ["model"], value_cols), metrics_dir / "moderate_metrics_summary.csv")
    write_csv(aggregate_over_seeds(ood_df, ["model"], value_cols), metrics_dir / "ood_metrics_summary.csv")
    aer_summary = aggregate_over_seeds(aer_df, ["model", "regime", "class"], ["aer", "post_perturbation_recall"])
    write_csv(aer_summary, metrics_dir / "aer_summary.csv")

    log.info("\n%s", aer_summary[(aer_summary["class"] == "overall")].to_string())

    # ---- Comparison plots ---------------------------------------------------
    plt.figure(figsize=(7, 4))
    summ = aggregate_over_seeds(clean_df, ["model"], ["macro_f1"])
    plt.bar(summ["model"], summ["macro_f1_mean"], yerr=summ["macro_f1_std"], capsize=4)
    plt.ylabel("Clean macro-F1 (mean +/- std, n=5 seeds)")
    plt.title("Clean macro-F1 by model")
    plt.tight_layout()
    plt.savefig(plots_dir / "clean_macro_f1_by_model.png", dpi=150)
    plt.close()

    plt.figure(figsize=(7, 4))
    aer_overall = aer_summary[(aer_summary["class"] == "overall") & (aer_summary["regime"] == "ood")]
    plt.bar(aer_overall["model"], aer_overall["aer_mean"], yerr=aer_overall["aer_std"], capsize=4, color="firebrick")
    plt.ylabel("OOD Attack Evasion Rate % (mean +/- std, n=5 seeds)")
    plt.title("OOD AER by model")
    plt.tight_layout()
    plt.savefig(plots_dir / "ood_aer_by_model.png", dpi=150)
    plt.close()

    # ---- Stage 4: non-circular SHAP attribution-drift audit (seed 42, OOD) --
    log.info("Running SHAP attribution-drift audit (M1 vs M4 vs M5, OOD, seed 42)...")
    m1, m4, m5 = seed42_models["m1"], seed42_models["m4"], seed42_models["m5"]
    ood_test_42 = attach_ratios(pd.read_parquet(settings.paths.processed_dir / "perturbed_ood_seed42.parquet"), bin_denom)
    y_pred_clean_m1 = m1.predict(test_df)
    y_pred_ood_m1 = m1.predict(ood_test_42)
    audit = build_audit_sample(
        y_true, y_pred_clean_m1, y_pred_ood_m1,
        cap_per_class=exp.shap_audit_cap_per_class, min_evaded=exp.shap_audit_min_evaded, seed=42,
    )
    write_csv(
        pd.DataFrame({"index": audit.indices, "true_class": [PROJECT_CLASSES[c] for c in audit.true_class]}),
        settings.paths.artifacts_dir / "data" / "audit_sample_ids.csv",
    )
    log.info("Audit set: %d flows; substitutions (fallback to random clean-detected): %s", len(audit.indices), audit.substituted_classes)

    drift_tables = {}
    for name, model, pert in (("m1", m1, ood_test_42), ("m4", m4, ood_test_42), ("m5", m5, ood_test_42)):
        drift_tables[name] = audit_attribution_drift(model, test_df, pert, audit)
    drift_all = pd.concat(drift_tables.values(), ignore_index=True)
    write_csv(drift_all, settings.paths.artifacts_dir / "data" / "shap_drift_table.csv")
    summary = group_summary(drift_tables)
    write_csv(summary, settings.paths.artifacts_dir / "data" / "shap_drift_group_summary.csv")
    log.info("\n%s", summary.to_string())

    # Representative true-class waterfall plot for M1 and M5, first audited flow.
    import shap

    for name, model in (("m1", m1), ("m5", m5)):
        idx = audit.indices[0]
        true_cls = int(audit.true_class[0])
        explainer = shap.TreeExplainer(model.estimator, model_output="raw")
        x_row = ood_test_42.iloc[[idx]][model.feature_list]
        sv = explainer.shap_values(x_row)
        sv_row = sv[true_cls][0] if isinstance(sv, list) else np.asarray(sv)[0, :, true_cls]
        base = explainer.expected_value[true_cls] if hasattr(explainer.expected_value, "__len__") else explainer.expected_value
        plt.figure()
        exp_obj = shap.Explanation(values=sv_row, base_values=base, data=x_row.iloc[0].to_numpy(), feature_names=model.feature_list)
        shap.plots.waterfall(exp_obj, show=False, max_display=12)
        plt.tight_layout()
        plt.savefig(settings.paths.artifacts_dir / "plots" / f"shap_waterfall_{name}.png", dpi=150)
        plt.close()

    run = RunRecord(settings.run_config_path)
    run.update("phase5", {
        "seeds": exp.seeds,
        "n_audited_flows": len(audit.indices),
        "audit_substituted_classes": audit.substituted_classes,
        "time_utc": utc_now(),
    })
    run.mark_phase_complete("phase5_full_evaluation")
    log.info("Phase 5 complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
