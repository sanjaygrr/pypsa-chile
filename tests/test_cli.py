import json

import pytest

from conftest import FIXTURES
from pypsa_chile import cli
from pypsa_chile.parse import read_capacity_by_region


@pytest.fixture
def data_dir(tmp_path):
    """A data directory laid out as `pypsa-chile fetch` would leave it."""
    import pandas as pd

    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    gen = pd.read_csv(FIXTURES / "generation_processed_excerpt.csv.gz", parse_dates=["time"])
    gen.to_csv(proc / "generation_2025.csv.gz", index=False, compression="gzip")
    read_capacity_by_region(FIXTURES / "capacity_by_region.xlsx").to_csv(
        proc / "capacity_by_region.csv", index=False
    )
    return tmp_path / "data"


def test_run_and_report(tmp_path, data_dir):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("thermal_availability:\n  window_days: 2\n")
    out = tmp_path / "results"
    rc = cli.main(["run", "-c", str(cfg), "--data-dir", str(data_dir), "--start", "2025-10-06",
                   "--end", "2025-10-06", "-o", str(out), "--report"])
    assert rc == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["period"][0].startswith("2025-10-06")
    html = (out / "report.html").read_text()
    assert "<html" in html and "plotly" in html.lower()
    assert "carrier_metrics.csv" in {p.name for p in out.iterdir()}


def test_run_without_data_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        cli.main(["run", "--data-dir", str(tmp_path / "nothing"), "-o", str(tmp_path / "r")])


def test_fetch_downloads_nothing_when_cached(tmp_path, data_dir, monkeypatch):
    """fetch reuses processed files and never touches the network for them."""
    from pypsa_chile import fetch as fetch_mod

    raw = data_dir / "raw"
    raw.mkdir()
    (raw / "CEN-hist_cap_inst_por_region_y_tecno.xlsx").write_bytes(
        (FIXTURES / "capacity_by_region.xlsx").read_bytes()
    )

    def no_network(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(fetch_mod.requests, "get", no_network)
    cfg = tmp_path / "c.yaml"
    cfg.write_text("thermal_availability:\n  window_days: 2\n")
    rc = cli.main(["fetch", "-c", str(cfg), "--data-dir", str(data_dir), "--start", "2025-10-06",
                   "--end", "2025-10-06"])
    assert rc == 0
