"""Vireo Audio support digest: deterministic pipeline + LLM issue classifier + static report."""
from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict:
    """Load config.yaml and resolve relative paths against the project root."""
    path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    root = path.resolve().parent
    cfg["paths"] = {k: (root / v) for k, v in cfg["paths"].items()}
    return cfg
