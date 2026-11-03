"""Load experiment configs and resolve project paths.

`load_config()` merges `configs/base.yaml` with an optional condition file. The data directory
comes from `MEDRAG_DATA_DIR` in `.env` if set (e.g. a non-synced folder), else `./data`.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "configs"

load_dotenv(PROJECT_ROOT / ".env")


def data_dir() -> Path:
    """Return the frozen data snapshot directory."""
    override = os.getenv("MEDRAG_DATA_DIR")
    return Path(override) if override else PROJECT_ROOT / "data"


def db_path() -> Path:
    """Return the path to the project DuckDB file."""
    return data_dir() / "project.duckdb"


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(condition: str | Path | None = None) -> dict:
    """Return base.yaml merged with a condition file (name in configs/ or a path)."""
    config = yaml.safe_load((CONFIG_DIR / "base.yaml").read_text())
    if condition is not None:
        path = Path(condition)
        if not path.suffix:
            path = CONFIG_DIR / f"{condition}.yaml"
        config = _merge(config, yaml.safe_load(path.read_text()) or {})
    return config
