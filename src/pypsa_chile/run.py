"""End-to-end run: build, solve, compare, write results."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from . import __version__
from .config import period
from .fetch import load_capacity, load_generation, load_manifest
from .network import available_by_zone, build_network, dispatch_by_zone, prices, solve, summarize_flows
from .validate import compare

log = logging.getLogger(__name__)


def _write_multi(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index_label="time")


def read_multi(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)


def run(cfg: dict, data_dir: Path, out_dir: Path) -> dict:
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    gen = load_generation(cfg, data_dir)
    cap = load_capacity(data_dir)
    n, info = build_network(cfg, gen, cap)
    del gen
    log.info("network: %d buses, %d generators, %d links, %d snapshots",
             len(n.buses), len(n.generators), len(n.links), len(n.snapshots))
    solve(n, cfg)

    simulated = dispatch_by_zone(n)
    available = available_by_zone(n)
    result = compare(info["observed"], simulated, available)

    _write_multi(info["observed"], out_dir / "observed.csv")
    _write_multi(simulated, out_dir / "simulated.csv")
    _write_multi(available, out_dir / "available.csv")
    prices(n).to_csv(out_dir / "prices.csv", index_label="time")
    n.links_t.p0.to_csv(out_dir / "flows.csv", index_label="time")
    summarize_flows(n).to_csv(out_dir / "flows_summary.csv", index_label="link")
    info["capacity"].to_csv(out_dir / "capacity.csv", index_label="zone")
    result["carrier_metrics"].to_csv(out_dir / "carrier_metrics.csv", index_label="carrier")
    result["zone_metrics"].to_csv(out_dir / "zone_metrics.csv", index_label="zone")

    start, end = period(cfg)
    summary = {
        "version": __version__,
        "period": [str(start), str(end)],
        "capacity_year": info["capacity_year"],
        "objective_usd": float(n.objective),
        "demand_gwh": float(info["demand"].sum() / 1e3),
        "load_shedding_gwh": result["load_shedding_gwh"],
        "model_curtailment_gwh": {k: float(v) for k, v in result["model_curtailment_gwh"].items()},
        "notes": info["notes"],
        "sources": load_manifest(data_dir),
        "config": cfg,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str),
                                          encoding="utf-8")
    return summary
