"""Config loading and seeding. All tunables live in config/*.yaml."""
from __future__ import annotations

import copy
import random
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "default.yaml"


def _deep_update(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_update(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    """Load default config, then an optional experiment file, then dict overrides."""
    with open(DEFAULT_CONFIG, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if path is not None:
        with open(path, "r", encoding="utf-8") as f:
            cfg = _deep_update(cfg, yaml.safe_load(f) or {})
    if overrides:
        cfg = _deep_update(cfg, overrides)
    return cfg


def to_ns(d):
    """Dict -> attribute-access namespace (recursive)."""
    if isinstance(d, dict):
        return SimpleNamespace(**{k: to_ns(v) for k, v in d.items()})
    return d


def seed_everything(seed: int) -> np.random.Generator:
    random.seed(seed)
    np.random.seed(seed)
    return np.random.default_rng(seed)
