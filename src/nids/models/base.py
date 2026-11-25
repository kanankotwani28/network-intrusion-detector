"""Shared LightGBM training wrapper used identically by M1-M5.

All five models use ``LGBMClassifier(class_weight='balanced')`` with
identical hyperparameters (proposal Appendix F); only the feature matrix
and the training rows differ between models, never the tuning. This module
is the single place that builds and fits the estimator so that guarantee is
enforced in code, not just in prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier

from nids.data.label_mapping import PROJECT_CLASSES
from nids.features.feature_groups import assert_no_target_columns


@dataclass
class TrainedModel:
    name: str
    seed: int
    feature_list: list[str]
    estimator: LGBMClassifier

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.estimator.predict(X[self.feature_list])

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.estimator.predict_proba(X[self.feature_list])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.estimator.booster_.save_model(str(path))


def build_estimator(params: dict, seed: int) -> LGBMClassifier:
    """Build an LGBMClassifier with the proposal's fixed hyperparameters.

    ``params`` must already carry ``class_weight='balanced'`` (enforced at
    config-load time by ``nids.config.settings.ModelConfig``); only the
    random seed varies per experimental run.
    """
    p = dict(params)
    if p.get("class_weight") != "balanced":
        raise ValueError("All five models must use class_weight='balanced'")
    return LGBMClassifier(random_state=seed, **p)


def fit_model(
    name: str,
    feature_list: list[str],
    train_df: pd.DataFrame,
    params: dict,
    seed: int,
    label_col: str = "y",
) -> TrainedModel:
    """Fit one model on ``train_df[feature_list]`` -> ``train_df[label_col]``."""
    assert_no_target_columns(feature_list)
    estimator = build_estimator(params, seed)
    estimator.fit(train_df[feature_list], train_df[label_col])
    return TrainedModel(name=name, seed=seed, feature_list=feature_list, estimator=estimator)


def feature_importance_table(model: TrainedModel) -> pd.DataFrame:
    imp = model.estimator.booster_.feature_importance(importance_type="gain")
    total = imp.sum()
    return (
        pd.DataFrame({"feature": model.feature_list, "gain_importance": imp})
        .assign(share=lambda d: d["gain_importance"] / total if total > 0 else 0.0)
        .sort_values("gain_importance", ascending=False)
        .reset_index(drop=True)
    )


CLASS_NAMES = PROJECT_CLASSES
