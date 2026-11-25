"""Run record (``run_config.json``) and software-version capture."""

from __future__ import annotations

import importlib.metadata as md
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nids.utils.io import read_json, write_json

_PACKAGES = [
    "numpy",
    "pandas",
    "pyarrow",
    "scikit-learn",
    "lightgbm",
    "shap",
    "matplotlib",
    "pydantic",
    "PyYAML",
    "tqdm",
]


def software_versions() -> dict[str, str]:
    """Versions actually installed in the running interpreter."""
    versions = {"python": sys.version.split()[0], "platform": platform.platform()}
    for pkg in _PACKAGES:
        try:
            versions[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            versions[pkg] = "not installed"
    return versions


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunRecord:
    """Incrementally updated ``run_config.json``.

    Each phase writes its own section, so the file always reflects what was
    actually executed (and when) rather than what was planned.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = read_json(path) if path.exists() else {}

    def update(self, section: str, payload: dict[str, Any]) -> None:
        self.data[section] = payload
        self.data.setdefault("completed_phases", [])
        self.data["software_versions"] = software_versions()
        self.data["last_updated_utc"] = utc_now()
        write_json(self.path, self.data)

    def mark_phase_complete(self, phase: str) -> None:
        phases = self.data.setdefault("completed_phases", [])
        entry = {"phase": phase, "completed_utc": utc_now()}
        self.data["completed_phases"] = [p for p in phases if p.get("phase") != phase] + [entry]
        write_json(self.path, self.data)
