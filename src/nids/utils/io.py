"""Small filesystem helpers: atomic-ish writes, JSON, checksums."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"Not JSON serialisable: {type(obj)!r}")


def write_json(path: Path, data: Any) -> Path:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=_json_default, sort_keys=False))
    tmp.replace(path)
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    ensure_dir(path.parent)
    df.to_csv(path, index=False)
    return path


def write_parquet(df: pd.DataFrame, path: Path) -> Path:
    ensure_dir(path.parent)
    df.to_parquet(path, index=False)
    return path


def sha256_file(path: Path, block_size: int = 1 << 22) -> str:
    """Streaming SHA-256 so large files never load into memory."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()
