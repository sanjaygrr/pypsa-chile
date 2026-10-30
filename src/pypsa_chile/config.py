"""Configuration loading."""

from __future__ import annotations

import copy
from importlib import resources
from pathlib import Path

import pandas as pd
import yaml


def default_config_path() -> Path:
    return Path(str(resources.files("pypsa_chile") / "data" / "default.yaml"))


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> dict:
    """Load the default config, optionally overridden by a user YAML file.

    The user file only needs the keys it changes.
    """
    with open(default_config_path(), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if path is not None:
        with open(path, encoding="utf-8") as f:
            cfg = _merge(cfg, yaml.safe_load(f) or {})
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict) -> None:
    start, end = period(cfg)
    if end < start:
        raise ValueError("period.end is before period.start")
    zones = set(cfg["zones"])
    shares = cfg["demand"]["zone_shares"]
    if set(shares) != zones:
        raise ValueError(f"demand.zone_shares must list exactly the zones {sorted(zones)}")
    total = sum(shares.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"demand.zone_shares must sum to 1, got {total:.4f}")
    for a, b, cap in cfg["transmission"]["links"]:
        if a not in zones or b not in zones:
            raise ValueError(f"transmission link {a}-{b} references an unknown zone")
        if cap < 0:
            raise ValueError(f"transmission link {a}-{b} has negative capacity")
    q = cfg["thermal_availability"].get("must_run_quantile")
    if q is not None and not 0 <= q <= 1:
        raise ValueError("thermal_availability.must_run_quantile must be between 0 and 1, or null")
    carriers = set(cfg["carriers"])
    unknown = set(cfg["carrier_map"].values()) - carriers
    if unknown:
        raise ValueError(f"carrier_map uses carriers not defined in carriers: {sorted(unknown)}")
    for name, spec in cfg["carriers"].items():
        if spec["kind"] not in {"profile", "budget", "thermal"}:
            raise ValueError(f"carrier {name} has unknown kind {spec['kind']!r}")


def period(cfg: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the first and last hour (inclusive) of the simulated period."""
    start = pd.Timestamp(cfg["period"]["start"])
    end = pd.Timestamp(cfg["period"]["end"]) + pd.Timedelta(hours=23)
    return start, end


def capacity_year(cfg: dict) -> int:
    value = cfg.get("capacity_year", "auto")
    if value == "auto":
        return period(cfg)[0].year - 1
    return int(value)
