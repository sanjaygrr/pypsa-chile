"""Compare simulated dispatch with observed generation."""

from __future__ import annotations

import numpy as np
import pandas as pd


def by_carrier(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse (zone, carrier) columns to system totals per carrier."""
    return df.T.groupby(level="carrier").sum().T


def by_zone(df: pd.DataFrame) -> pd.DataFrame:
    return df.T.groupby(level="zone").sum().T


def error_metrics(observed: pd.DataFrame, simulated: pd.DataFrame) -> pd.DataFrame:
    """Hourly error metrics per column.

    Both inputs are hourly MW tables on the same index. Columns missing on
    one side are treated as zero. Energies are in GWh, errors in MW.
    ``nmae`` is MAE divided by mean observed output; it is undefined when the
    observed mean is zero.
    """
    cols = sorted(set(observed.columns) | set(simulated.columns))
    obs = observed.reindex(columns=cols, fill_value=0.0)
    sim = simulated.reindex(index=obs.index, columns=cols, fill_value=0.0)
    err = sim - obs
    mean_obs = obs.mean()
    out = pd.DataFrame({
        "observed_gwh": obs.sum() / 1e3,
        "simulated_gwh": sim.sum() / 1e3,
        "bias_mw": err.mean(),
        "mae_mw": err.abs().mean(),
        "rmse_mw": np.sqrt((err**2).mean()),
        "nmae": (err.abs().mean() / mean_obs.where(mean_obs > 0)),
        "correlation": [obs[c].corr(sim[c]) if obs[c].std() > 0 and sim[c].std() > 0 else np.nan for c in cols],
    })
    out["energy_error_pct"] = 100 * (out["simulated_gwh"] - out["observed_gwh"]) / out["observed_gwh"].where(
        out["observed_gwh"] > 0
    )
    return out


def compare(observed: pd.DataFrame, simulated: pd.DataFrame, available: pd.DataFrame) -> dict:
    """System-level and zonal comparison tables."""
    zones = sorted(set(simulated.columns.get_level_values("zone")))
    obs_in_model = observed.loc[:, observed.columns.get_level_values("zone").isin(zones)]
    carrier_obs = by_carrier(observed)
    carrier_sim = by_carrier(simulated.drop(columns="load_shedding", level="carrier", errors="ignore"))

    curtail = (available - simulated.reindex(columns=available.columns, fill_value=0.0)).clip(lower=0)
    curtail = by_carrier(curtail)
    curtail = curtail[[c for c in ("solar", "wind", "hydro_ror") if c in curtail.columns]]

    shed = simulated.xs("load_shedding", level="carrier", axis=1) if "load_shedding" in simulated.columns.get_level_values("carrier") else None

    return {
        "carrier_observed": carrier_obs,
        "carrier_simulated": carrier_sim,
        "carrier_metrics": error_metrics(carrier_obs, carrier_sim),
        "zone_metrics": error_metrics(
            by_zone(obs_in_model),
            by_zone(simulated.drop(columns="load_shedding", level="carrier", errors="ignore")),
        ),
        "model_curtailment_gwh": curtail.sum() / 1e3,
        "load_shedding_gwh": float(shed.sum().sum() / 1e3) if shed is not None else 0.0,
    }
