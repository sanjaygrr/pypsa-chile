"""Download raw CEN files and turn them into small processed tables."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from pathlib import Path

import pandas as pd
import requests

from .config import period
from .parse import read_capacity_by_region, read_generation_by_unit

log = logging.getLogger(__name__)

USER_AGENT = "pypsa-chile (+https://github.com/sanjaygrr/pypsa-chile)"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_path(data_dir: Path) -> Path:
    return data_dir / "raw" / "manifest.json"


def load_manifest(data_dir: Path) -> dict:
    path = _manifest_path(data_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def download(url: str, data_dir: Path, force: bool = False) -> Path:
    """Download ``url`` into ``data_dir/raw`` and record it in the manifest."""
    raw = data_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    dest = raw / url.rsplit("/", 1)[-1]
    if dest.exists() and not force:
        log.info("using cached %s", dest.name)
        return dest
    log.info("downloading %s", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    with open(tmp, "rb") as f:
        if f.read(2) != b"PK":
            tmp.unlink()
            raise RuntimeError(f"{url} did not return an xlsx file")
    tmp.replace(dest)
    manifest = load_manifest(data_dir)
    manifest[dest.name] = {
        "url": url,
        "sha256": _sha256(dest),
        "bytes": dest.stat().st_size,
        "downloaded_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    _manifest_path(data_dir).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return dest


def years_needed(cfg: dict) -> list[int]:
    """Calendar years covered by the period plus the thermal look-back window."""
    start, end = period(cfg)
    window = int(cfg["thermal_availability"].get("window_days", 0))
    first = (start - pd.Timedelta(days=window)).year
    return list(range(first, end.year + 1))


def generation_path(data_dir: Path, year: int) -> Path:
    return data_dir / "processed" / f"generation_{year}.csv.gz"


def capacity_path(data_dir: Path) -> Path:
    return data_dir / "processed" / "capacity_by_region.csv"


def fetch(cfg: dict, data_dir: Path, force: bool = False) -> list[Path]:
    """Download and process every file the configured period needs."""
    data_dir = Path(data_dir)
    (data_dir / "processed").mkdir(parents=True, exist_ok=True)
    written = []

    cap_raw = download(cfg["sources"]["capacity_by_region"], data_dir, force)
    cap = read_capacity_by_region(cap_raw)
    cap.to_csv(capacity_path(data_dir), index=False)
    written.append(capacity_path(data_dir))

    urls = {int(k): v for k, v in cfg["sources"]["generation_by_unit"].items()}
    for year in years_needed(cfg):
        if year not in urls:
            raise KeyError(
                f"no generation file configured for {year}; add it under sources.generation_by_unit"
            )
        out = generation_path(data_dir, year)
        if out.exists() and not force:
            log.info("using cached %s", out.name)
            written.append(out)
            continue
        raw = download(urls[year], data_dir, force)
        log.info("parsing %s (this takes a few minutes)", raw.name)
        gen = read_generation_by_unit(raw, year=year)
        if gen.attrs.get("unknown_regions"):
            log.warning("unrecognised regions: %s", gen.attrs["unknown_regions"])
        if gen.attrs.get("hour25_mwh"):
            log.warning("%.0f MWh reported in a 25th hour (end of daylight saving) left out",
                        gen.attrs["hour25_mwh"])
        gen = gen[gen["time"].dt.year == year]
        gen.to_csv(out, index=False, compression="gzip")
        written.append(out)
    return written


def load_generation(cfg: dict, data_dir: Path) -> pd.DataFrame:
    frames = []
    for year in years_needed(cfg):
        path = generation_path(Path(data_dir), year)
        if not path.exists():
            raise FileNotFoundError(f"{path} missing, run `pypsa-chile fetch` first")
        frames.append(pd.read_csv(path, parse_dates=["time"]))
    return pd.concat(frames, ignore_index=True)


def load_capacity(data_dir: Path) -> pd.DataFrame:
    path = capacity_path(Path(data_dir))
    if not path.exists():
        raise FileNotFoundError(f"{path} missing, run `pypsa-chile fetch` first")
    return pd.read_csv(path)
