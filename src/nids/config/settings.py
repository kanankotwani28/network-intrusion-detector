"""Typed, validated experiment configuration.

All experiment parameters live in ``configs/experiment.yaml``. This module
loads that file into Pydantic models so that a typo or an out-of-range value
fails immediately instead of silently changing an experiment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

REPO_ROOT = Path(__file__).resolve().parents[3]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathsConfig(_Strict):
    raw_dataset: Path
    interim_dir: Path
    processed_dir: Path
    artifacts_dir: Path

    def resolved(self, base: Path) -> "PathsConfig":
        """Return a copy with relative paths made absolute against ``base``."""

        def fix(p: Path) -> Path:
            return p if p.is_absolute() else (base / p).resolve()

        return PathsConfig(**{k: fix(v) for k, v in self.model_dump().items()})


class DataConfig(_Strict):
    chunksize: int = Field(200_000, gt=0)
    sample_size: int = Field(100_000, gt=0)
    sampling_seed: int = 42
    split_seed: int = 42
    test_size: float = Field(0.30, gt=0.0, lt=1.0)
    conflict_rate_threshold: float = Field(0.01, ge=0.0, le=1.0)
    halt_on_conflict_threshold: bool = True
    halt_on_unknown_labels: bool = True
    compute_checksum: bool = True


class IdentityCheckConfig(_Strict):
    relative_tolerance: float = Field(0.05, gt=0.0)
    min_pass_rate: float = Field(0.95, gt=0.0, le=1.0)


class ModelConfig(_Strict):
    params: dict[str, Any]

    @field_validator("params")
    @classmethod
    def _no_seed_in_params(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "random_state" in v or "seed" in v:
            raise ValueError("random_state is set per experimental seed; do not put it in params")
        if v.get("class_weight") != "balanced":
            raise ValueError("Proposal requires class_weight='balanced' for all five models")
        return v


class ExperimentConfig(_Strict):
    seeds: list[int]
    noise_sigma: float = Field(0.10, gt=0.0)
    alpha_train: tuple[float, float]
    alpha_moderate: tuple[float, float]
    alpha_ood: tuple[float, float]
    shap_threshold: float = Field(0.025, gt=0.0, lt=1.0)
    shap_sensitivity_thresholds: list[float]
    shap_selection_cap_per_class: int = Field(2500, gt=0)
    shap_audit_cap_per_class: int = Field(300, gt=0)
    shap_audit_min_evaded: int = Field(30, gt=0)
    low_support_threshold: int = Field(200, gt=0)

    @field_validator("alpha_train", "alpha_moderate", "alpha_ood")
    @classmethod
    def _valid_alpha(cls, v: tuple[float, float]) -> tuple[float, float]:
        lo, hi = v
        if not (1.0 <= lo < hi):
            raise ValueError(f"alpha range must satisfy 1 <= low < high, got {v}")
        return v

    @field_validator("seeds")
    @classmethod
    def _unique_seeds(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v) or not v:
            raise ValueError("seeds must be a non-empty list of distinct integers")
        return v


class Settings(_Strict):
    run_name: str
    paths: PathsConfig
    data: DataConfig
    identity_checks: IdentityCheckConfig = IdentityCheckConfig()
    model: ModelConfig
    experiment: ExperimentConfig

    # Convenience output locations ---------------------------------------
    @property
    def data_reports_dir(self) -> Path:
        return self.paths.artifacts_dir / "data"

    @property
    def run_config_path(self) -> Path:
        return self.paths.artifacts_dir / "run_config.json"


def load_settings(config_path: str | Path, overrides: dict[str, Any] | None = None) -> Settings:
    """Load and validate a YAML config.

    Relative paths are resolved against the repository root (the parent of
    the ``configs/`` directory containing the file).

    Parameters
    ----------
    config_path:
        Path to the YAML file.
    overrides:
        Optional nested dict merged over the YAML contents (e.g. from CLI).

    Relative paths inside the config resolve against the current working
    directory (scripts in this repo are run from the repository root).
    """
    config_path = Path(config_path).resolve()
    raw = yaml.safe_load(config_path.read_text())
    if overrides:
        raw = _deep_merge(raw, overrides)
    settings = Settings(**raw)
    base = Path.cwd()
    return settings.model_copy(update={"paths": settings.paths.resolved(base)})


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
