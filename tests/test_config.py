import pandas as pd
import pytest

from pypsa_chile.config import capacity_year, load_config, period, validate_config


def test_default_config_is_valid():
    cfg = load_config()
    assert set(cfg["demand"]["zone_shares"]) == set(cfg["zones"])


def test_period_is_inclusive():
    cfg = load_config()
    start, end = period(cfg)
    assert (end - start) == pd.Timedelta(days=6, hours=23)


def test_capacity_year_auto():
    cfg = load_config()
    assert capacity_year(cfg) == 2024
    cfg["capacity_year"] = 2023
    assert capacity_year(cfg) == 2023


def test_override_file(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("period:\n  start: '2025-03-01'\n  end: '2025-03-02'\n")
    cfg = load_config(p)
    assert cfg["period"]["start"] == "2025-03-01"
    assert cfg["solver"]["name"] == "highs"  # untouched keys kept


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["demand"]["zone_shares"].update(centro=0.9),
        lambda c: c["transmission"]["links"].append(["centro", "mars", 10.0]),
        lambda c: c["carrier_map"].update({"X/Y": "fusion"}),
        lambda c: c["period"].update(start="2025-02-01", end="2025-01-01"),
        lambda c: c["thermal_availability"].update(must_run_quantile=2),
    ],
)
def test_invalid_configs(mutate):
    cfg = load_config()
    mutate(cfg)
    with pytest.raises(ValueError):
        validate_config(cfg)
