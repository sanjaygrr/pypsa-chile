import pandas as pd
import pytest

from pypsa_chile.network import (
    available_by_zone,
    build_network,
    capacity_by_zone,
    dispatch_by_zone,
    observed_by_zone,
    solve,
)
from pypsa_chile.validate import by_carrier, compare, error_metrics


def test_capacity_by_zone(cfg, capacity):
    table = capacity_by_zone(capacity, cfg, 2024)
    assert list(table.index) == list(cfg["zones"])
    # zones cover all 14 regions of the file, so totals are preserved
    total = capacity[capacity["year"] == 2024]["mw"].sum()
    assert table.to_numpy().sum() == pytest.approx(total)


def test_capacity_missing_year(cfg, capacity):
    with pytest.raises(ValueError):
        capacity_by_zone(capacity, cfg, 1990)


def test_observed_by_zone_preserves_energy(cfg, generation):
    obs = observed_by_zone(generation, cfg)
    assert obs.to_numpy().sum() == pytest.approx(generation["mwh"].sum())


def test_unmapped_type_raises(cfg, generation):
    g = generation.copy()
    g.loc[g.index[0], "subtipo"] = "Fusion"
    with pytest.raises(ValueError, match="carrier_map"):
        observed_by_zone(g, cfg)


def test_build_requires_lookback(cfg, generation, capacity):
    cfg["thermal_availability"]["window_days"] = 30
    with pytest.raises(ValueError, match="window"):
        build_network(cfg, generation, capacity)


@pytest.fixture(scope="module")
def solved(request):
    from pypsa_chile.config import load_config
    from conftest import FIXTURES
    from pypsa_chile.parse import read_capacity_by_region

    c = load_config()
    c["period"] = {"start": "2025-10-06", "end": "2025-10-06"}
    c["thermal_availability"]["window_days"] = 2
    gen = pd.read_csv(FIXTURES / "generation_processed_excerpt.csv.gz", parse_dates=["time"])
    cap = read_capacity_by_region(FIXTURES / "capacity_by_region.xlsx")
    n, info = build_network(c, gen, cap)
    solve(n, c)
    return c, n, info


def test_network_structure(solved):
    cfg, n, info = solved
    assert len(n.snapshots) == 24
    assert set(n.buses.index) == set(cfg["zones"])
    assert len(n.links) == len(cfg["transmission"]["links"])


def test_energy_balance(solved):
    cfg, n, info = solved
    sim = dispatch_by_zone(n)
    # total generation (incl. unserved) equals demand every hour; links are lossless
    assert sim.sum(axis=1).to_numpy() == pytest.approx(info["demand"].to_numpy(), rel=1e-6)
    shares = pd.Series(cfg["demand"]["zone_shares"])
    assert n.loads_t.p_set.sum().sum() == pytest.approx(info["demand"].sum() * shares.sum())


def test_limits_respected(solved):
    cfg, n, info = solved
    sim = dispatch_by_zone(n)
    avail = available_by_zone(n)
    assert (sim.reindex(columns=avail.columns) <= avail + 1e-4).all().all()
    for name, link in n.links.iterrows():
        assert n.links_t.p0[name].abs().max() <= link.p_nom + 1e-4


def test_budget_energy_not_exceeded(solved):
    cfg, n, info = solved
    sim = by_carrier(dispatch_by_zone(n))
    obs = by_carrier(info["observed"])
    assert sim["hydro_reservoir"].sum() <= obs["hydro_reservoir"].sum() + 1e-3


def test_profile_carriers_follow_observation(solved):
    """With no binding constraint the model uses all free solar, wind and ROR."""
    cfg, n, info = solved
    sim = by_carrier(dispatch_by_zone(n))
    obs = by_carrier(info["observed"])
    for c in ("solar", "wind", "hydro_ror"):
        assert sim[c].sum() <= obs[c].clip(lower=0).sum() + 1e-3


def test_compare_outputs(solved):
    cfg, n, info = solved
    res = compare(info["observed"], dispatch_by_zone(n), available_by_zone(n))
    m = res["carrier_metrics"]
    assert {"mae_mw", "rmse_mw", "nmae", "observed_gwh", "simulated_gwh"} <= set(m.columns)
    assert (m["rmse_mw"] >= m["mae_mw"] - 1e-9).all()
    assert res["load_shedding_gwh"] >= 0


def test_error_metrics_known_values():
    idx = pd.date_range("2025-01-01", periods=4, freq="h")
    obs = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    sim = pd.DataFrame({"a": [2.0, 2.0, 2.0, 4.0]}, index=idx)
    m = error_metrics(obs, sim).loc["a"]
    assert m["mae_mw"] == pytest.approx(0.5)
    assert m["rmse_mw"] == pytest.approx((2 / 4) ** 0.5)
    assert m["bias_mw"] == pytest.approx(0.0)
    assert m["nmae"] == pytest.approx(0.5 / 2.5)
    assert m["observed_gwh"] == pytest.approx(10 / 1e3)
