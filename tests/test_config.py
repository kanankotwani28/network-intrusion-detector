import pytest

from nids.config.settings import load_settings


def test_default_config_loads_and_validates():
    settings = load_settings("configs/experiment.yaml")
    assert settings.data.sample_size == 100_000
    assert settings.experiment.seeds == [42, 101, 202, 303, 404]
    assert settings.paths.raw_dataset.is_absolute()


def test_model_params_require_balanced_class_weight(tmp_path):
    import yaml

    bad = {
        "run_name": "x",
        "paths": {
            "raw_dataset": "data/raw/x.csv",
            "interim_dir": "data/interim",
            "processed_dir": "data/processed",
            "artifacts_dir": "artifacts",
        },
        "data": {},
        "model": {"params": {"n_estimators": 10, "class_weight": "none"}},
        "experiment": {
            "seeds": [1],
            "alpha_train": [1.5, 2.5],
            "alpha_moderate": [1.5, 2.5],
            "alpha_ood": [3.0, 4.5],
            "shap_sensitivity_thresholds": [0.01, 0.05],
        },
    }
    p = tmp_path / "configs" / "bad.yaml"
    p.parent.mkdir()
    p.write_text(yaml.dump(bad))
    with pytest.raises(Exception):
        load_settings(p)


def test_alpha_range_must_be_increasing(tmp_path):
    import yaml

    bad = {
        "run_name": "x",
        "paths": {
            "raw_dataset": "data/raw/x.csv",
            "interim_dir": "data/interim",
            "processed_dir": "data/processed",
            "artifacts_dir": "artifacts",
        },
        "data": {},
        "model": {"params": {"n_estimators": 10, "class_weight": "balanced"}},
        "experiment": {
            "seeds": [1],
            "alpha_train": [2.5, 1.5],
            "alpha_moderate": [1.5, 2.5],
            "alpha_ood": [3.0, 4.5],
            "shap_sensitivity_thresholds": [0.01, 0.05],
        },
    }
    p = tmp_path / "configs" / "bad2.yaml"
    p.parent.mkdir()
    p.write_text(yaml.dump(bad))
    with pytest.raises(Exception):
        load_settings(p)
