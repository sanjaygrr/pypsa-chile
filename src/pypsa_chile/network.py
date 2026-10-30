"""Build and solve the zonal PyPSA network."""

from __future__ import annotations

import logging

import pandas as pd
import pypsa

from .config import capacity_year, period
from .parse import normalize_region

log = logging.getLogger(__name__)

HYDRO = ("hydro_ror", "hydro_reservoir")


def region_to_zone(cfg: dict) -> dict[str, str]:
    mapping = {}
    for zone, regions in cfg["zones"].items():
        for region in regions:
            mapping[normalize_region(region)] = zone
    return mapping


def observed_by_zone(gen: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Hourly observed generation (MW) with columns (zone, carrier).

    Regions outside every zone are kept under the zone "unassigned" so that
    system totals still match the source file.
    """
    zone_of = region_to_zone(cfg)
    label = gen["tipo"].astype(str) + "/" + gen["subtipo"].astype(str)
    unmapped = sorted(set(label) - set(cfg["carrier_map"]))
    if unmapped:
        raise ValueError(f"generation types without a carrier_map entry: {unmapped}")
    df = pd.DataFrame(
        {
            "time": gen["time"],
            "zone": gen["region"].map(zone_of).fillna("unassigned"),
            "carrier": label.map(cfg["carrier_map"]),
            "mw": gen["mwh"],
        }
    )
    out = df.pivot_table(index="time", columns=["zone", "carrier"], values="mw", aggfunc="sum")
    return out.fillna(0.0).sort_index(axis=1)


def capacity_by_zone(cap: pd.DataFrame, cfg: dict, year: int) -> pd.DataFrame:
    """Installed capacity (MW), zones as rows and capacity groups as columns."""
    sel = cap[cap["year"] == year]
    if sel.empty:
        raise ValueError(f"no capacity data for year {year}; available: {sorted(cap['year'].unique())}")
    zone_of = region_to_zone(cfg)
    sel = sel.assign(
        zone=sel["region"].map(zone_of),
        group=sel["technology"].map(cfg["capacity_columns"]),
    )
    missing = sorted(sel.loc[sel["zone"].isna(), "region"].unique())
    if missing:
        log.warning("capacity regions outside every zone, ignored: %s", missing)
    table = sel.dropna(subset=["zone", "group"]).pivot_table(
        index="zone", columns="group", values="mw", aggfunc="sum"
    )
    return table.reindex(index=list(cfg["zones"]), columns=sorted(set(cfg["capacity_columns"].values()))).fillna(0.0)


def _series(obs: pd.DataFrame, zone: str, carrier: str, index: pd.Index) -> pd.Series:
    if (zone, carrier) in obs.columns:
        return obs[(zone, carrier)].reindex(index).fillna(0.0)
    return pd.Series(0.0, index=index)


def build_network(cfg: dict, gen: pd.DataFrame, cap: pd.DataFrame) -> tuple[pypsa.Network, dict]:
    """Return the network and a dict with the observed data used to build it."""
    start, end = period(cfg)
    snapshots = pd.date_range(start, end, freq="h")
    obs_all = observed_by_zone(gen, cfg)
    missing = snapshots.difference(obs_all.index)
    if len(missing):
        raise ValueError(f"{len(missing)} hours of the period have no observed data, first: {missing[0]}")
    obs = obs_all.loc[snapshots]

    year = capacity_year(cfg)
    capacity = capacity_by_zone(cap, cfg, year)
    window = int(cfg["thermal_availability"]["window_days"])
    look_back = obs_all.loc[(obs_all.index >= start - pd.Timedelta(days=window)) & (obs_all.index < start)]
    if window and len(look_back) < window * 24 * 0.9:
        raise ValueError(
            f"only {len(look_back)} hours available for the {window}-day availability window; "
            "fetch the previous year as well"
        )

    must_run_q = cfg["thermal_availability"].get("must_run_quantile")
    notes: list[str] = []
    n = pypsa.Network()
    n.set_snapshots(snapshots)
    for carrier in list(cfg["carriers"]) + ["load_shedding", "AC", "DC"]:
        n.add("Carrier", carrier)

    demand = obs.T.groupby(level="carrier").sum().T.sum(axis=1)
    shares = cfg["demand"]["zone_shares"]
    cap_group = {
        "solar": "solar", "wind": "wind", "csp": "csp", "geothermal": "geothermal",
        "coal": "coal", "gas": "gas", "diesel": "diesel", "other_thermal": "other_thermal",
    }

    for zone in cfg["zones"]:
        n.add("Bus", zone, carrier="AC")
        n.add("Load", f"{zone} load", bus=zone, p_set=demand * shares[zone])
        n.add(
            "Generator", f"{zone} load_shedding", bus=zone, carrier="load_shedding",
            p_nom=demand.max(), marginal_cost=float(cfg["demand"]["voll"]),
        )

        for carrier, spec in cfg["carriers"].items():
            if carrier in HYDRO:
                continue
            kind = spec["kind"]
            mc = float(spec["marginal_cost"])
            installed = float(capacity.loc[zone].get(cap_group.get(carrier, carrier), 0.0))
            o = _series(obs, zone, carrier, snapshots)
            name = f"{zone} {carrier}"

            if kind == "profile":
                p_nom = max(installed, float(o.max()))
                if p_nom <= 0:
                    continue
                if o.max() > installed + 1e-6:
                    notes.append(
                        f"{name}: observed peak {o.max():.0f} MW exceeds {year} capacity "
                        f"{installed:.0f} MW; capacity raised to the observed peak."
                    )
                n.add("Generator", name, bus=zone, carrier=carrier, p_nom=p_nom,
                      p_max_pu=(o.clip(lower=0) / p_nom), marginal_cost=mc)

            elif kind == "budget":
                energy = float(o.clip(lower=0).sum())
                p_nom = max(installed, float(o.max()))
                if p_nom <= 0 or energy <= 0:
                    continue
                n.add("Generator", name, bus=zone, carrier=carrier, p_nom=p_nom,
                      marginal_cost=mc, e_sum_max=energy)

            else:  # thermal
                lb = look_back[(zone, carrier)] if (zone, carrier) in look_back.columns else pd.Series(dtype=float)
                peak = float(lb.max()) if len(lb) else 0.0
                p_nom = installed
                if installed <= 0 and peak > 0:
                    p_nom = peak
                    notes.append(f"{name}: no capacity in the {year} file but {peak:.0f} MW observed "
                                 "in the look-back window; that peak is used as capacity.")
                if p_nom <= 0:
                    continue
                avail = min(1.0, peak / p_nom)
                must_run = 0.0
                if must_run_q is not None and len(lb):
                    must_run = min(avail, max(0.0, float(lb.quantile(must_run_q))) / p_nom)
                n.add("Generator", name, bus=zone, carrier=carrier, p_nom=p_nom,
                      p_max_pu=avail, p_min_pu=must_run, marginal_cost=mc)

        # Hydro: one installed capacity shared by run-of-river and reservoir.
        ror = _series(obs, zone, "hydro_ror", snapshots).clip(lower=0)
        res = _series(obs, zone, "hydro_reservoir", snapshots).clip(lower=0)
        c_hydro = float(capacity.loc[zone].get("hydro", 0.0))
        peak = float((ror + res).max())
        if peak > c_hydro + 1e-6:
            notes.append(f"{zone} hydro: observed peak {peak:.0f} MW exceeds {year} capacity "
                         f"{c_hydro:.0f} MW; capacity raised to the observed peak.")
            c_hydro = peak
        if c_hydro > 0:
            if ror.max() > 0:
                n.add("Generator", f"{zone} hydro_ror", bus=zone, carrier="hydro_ror", p_nom=c_hydro,
                      p_max_pu=ror / c_hydro,
                      marginal_cost=float(cfg["carriers"]["hydro_ror"]["marginal_cost"]))
            if res.sum() > 0:
                n.add("Generator", f"{zone} hydro_reservoir", bus=zone, carrier="hydro_reservoir",
                      p_nom=c_hydro, p_max_pu=((c_hydro - ror) / c_hydro).clip(lower=0),
                      e_sum_max=float(res.sum()),
                      marginal_cost=float(cfg["carriers"]["hydro_reservoir"]["marginal_cost"]))

    for a, b, s_nom in cfg["transmission"]["links"]:
        n.add("Link", f"{a}-{b}", bus0=a, bus1=b, carrier="DC", p_nom=float(s_nom), p_min_pu=-1.0,
              efficiency=1.0)

    unassigned = [c for c in obs.columns if c[0] == "unassigned"]
    if unassigned:
        energy = obs[unassigned].sum().sum()
        notes.append(f"{energy:.0f} MWh of observed generation is in regions outside every zone; "
                     "it is counted in demand and in the observed totals only.")

    info = {
        "observed": obs,
        "demand": demand,
        "capacity": capacity,
        "capacity_year": year,
        "notes": notes,
    }
    return n, info


def solve(n: pypsa.Network, cfg: dict) -> None:
    solver = cfg["solver"]
    status, condition = n.optimize(solver_name=solver["name"], solver_options=solver.get("options", {}))
    if status != "ok":
        raise RuntimeError(f"optimisation failed: {status} / {condition}")


def dispatch_by_zone(n: pypsa.Network) -> pd.DataFrame:
    """Simulated generation (MW) with columns (zone, carrier)."""
    p = n.generators_t.p
    gens = n.generators.loc[p.columns]
    cols = pd.MultiIndex.from_arrays([gens["bus"], gens["carrier"]], names=["zone", "carrier"])
    out = p.copy()
    out.columns = cols
    return out.T.groupby(level=["zone", "carrier"]).sum().T


def available_by_zone(n: pypsa.Network) -> pd.DataFrame:
    """Available power (MW) for every generator, columns (zone, carrier)."""
    g = n.generators
    pu = n.get_switchable_as_dense("Generator", "p_max_pu")
    avail = pu * g["p_nom"]
    avail.columns = pd.MultiIndex.from_arrays([g["bus"], g["carrier"]], names=["zone", "carrier"])
    return avail.T.groupby(level=["zone", "carrier"]).sum().T


def summarize_flows(n: pypsa.Network) -> pd.DataFrame:
    flows = n.links_t.p0.copy()
    stats = pd.DataFrame({
        "p_nom_mw": n.links["p_nom"],
        "mean_flow_mw": flows.mean(),
        "max_abs_flow_mw": flows.abs().max(),
        "hours_at_limit": (flows.abs() >= n.links["p_nom"] - 1e-3).sum(),
    })
    return stats


def prices(n: pypsa.Network) -> pd.DataFrame:
    return n.buses_t.marginal_price.copy()

