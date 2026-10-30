"""Static HTML report with the comparison between model and observations."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .run import read_multi
from .validate import by_carrier

COLORS = {
    "solar": "#f2b701",
    "csp": "#e07b00",
    "wind": "#4c9be8",
    "hydro_ror": "#2a6f97",
    "hydro_reservoir": "#013a63",
    "geothermal": "#9c6644",
    "coal": "#3d3d3d",
    "gas": "#d1495b",
    "other_thermal": "#8d6a9f",
    "diesel": "#7a1e1e",
    "load_shedding": "#ff00ff",
}
ORDER = list(COLORS)

LABELS = {
    "solar": "Solar PV", "csp": "Concentrated solar", "wind": "Wind",
    "hydro_ror": "Hydro, run-of-river", "hydro_reservoir": "Hydro, reservoir",
    "geothermal": "Geothermal", "coal": "Coal", "gas": "Natural gas",
    "other_thermal": "Other thermal", "diesel": "Diesel", "load_shedding": "Unserved load",
}


def _ordered(cols) -> list[str]:
    return [c for c in ORDER if c in cols] + sorted(c for c in cols if c not in ORDER)


def _fig_html(fig: go.Figure, first: bool) -> str:
    fig.update_layout(template="plotly_white", margin=dict(l=60, r=20, t=50, b=40),
                      font=dict(family="system-ui, sans-serif", size=13))
    return fig.to_html(full_html=False, include_plotlyjs=True if first else False,
                       config={"displaylogo": False, "responsive": True})


def _stack_figure(obs: pd.DataFrame, sim: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, shared_yaxes=True, vertical_spacing=0.08,
                        subplot_titles=("Observed (CEN)", "Simulated"))
    for row, df in ((1, obs), (2, sim)):
        for c in _ordered(df.columns):
            if df[c].abs().sum() == 0:
                continue
            fig.add_trace(go.Scatter(
                x=df.index, y=df[c].clip(lower=0), name=LABELS.get(c, c), stackgroup=f"s{row}",
                line=dict(width=0), fillcolor=COLORS.get(c), legendgroup=c, showlegend=row == 1,
                hovertemplate="%{y:,.0f} MW",
            ), row=row, col=1)
    fig.update_yaxes(title_text="MW")
    fig.update_layout(height=650, title="Hourly generation by technology, whole system",
                      hovermode="x unified")
    return fig


def _carrier_lines(obs: pd.DataFrame, sim: pd.DataFrame) -> go.Figure:
    carriers = [c for c in _ordered(set(obs.columns) | set(sim.columns))
                if obs.get(c, pd.Series(0)).abs().sum() + sim.get(c, pd.Series(0)).abs().sum() > 0
                and c != "load_shedding"]
    rows = (len(carriers) + 1) // 2
    fig = make_subplots(rows=rows, cols=2, shared_xaxes=True, vertical_spacing=0.06,
                        subplot_titles=[LABELS.get(c, c) for c in carriers])
    for i, c in enumerate(carriers):
        r, k = i // 2 + 1, i % 2 + 1
        color = COLORS.get(c, "#555")
        fig.add_trace(go.Scatter(x=obs.index, y=obs.get(c, 0 * obs.iloc[:, 0]), name="observed",
                                 line=dict(color=color, width=2), legendgroup="obs",
                                 showlegend=i == 0), row=r, col=k)
        fig.add_trace(go.Scatter(x=sim.index, y=sim.get(c, 0 * sim.iloc[:, 0]), name="simulated",
                                 line=dict(color="#222", width=1.3, dash="dot"), legendgroup="sim",
                                 showlegend=i == 0), row=r, col=k)
    fig.update_layout(height=230 * rows, title="Observed vs simulated, per technology (MW)")
    return fig


def _energy_bars(metrics: pd.DataFrame) -> go.Figure:
    m = metrics.loc[_ordered(metrics.index)]
    labels = [LABELS.get(c, c) for c in m.index]
    fig = go.Figure([
        go.Bar(x=labels, y=m["observed_gwh"], name="observed", marker_color="#2a6f97"),
        go.Bar(x=labels, y=m["simulated_gwh"], name="simulated", marker_color="#d1495b"),
    ])
    fig.update_layout(barmode="group", height=420, title="Energy over the period (GWh)",
                      yaxis_title="GWh")
    return fig


def _price_figure(prices: pd.DataFrame) -> go.Figure:
    fig = go.Figure([go.Scatter(x=prices.index, y=prices[c], name=c, mode="lines") for c in prices.columns])
    fig.update_layout(height=380, title="Zonal marginal prices of the model (USD/MWh)",
                      yaxis_title="USD/MWh", hovermode="x unified")
    return fig


def _flow_figure(flows: pd.DataFrame, limits: pd.Series) -> go.Figure:
    fig = go.Figure()
    for c in flows.columns:
        fig.add_trace(go.Scatter(x=flows.index, y=flows[c], name=f"{c} (limit {limits[c]:,.0f} MW)",
                                 mode="lines"))
    fig.update_layout(height=380, title="Inter-zonal flows, positive from first to second zone (MW)",
                      yaxis_title="MW", hovermode="x unified")
    return fig


HEADERS = {
    "observed_gwh": "Observed (GWh)", "simulated_gwh": "Simulated (GWh)", "bias_mw": "Bias (MW)",
    "mae_mw": "MAE (MW)", "rmse_mw": "RMSE (MW)", "nmae": "nMAE", "correlation": "Correlation",
    "energy_error_pct": "Energy error (%)", "marginal_cost": "Marginal cost", "kind": "Representation",
}


def _table(df: pd.DataFrame, fmt: dict[str, str], index_label: str) -> str:
    head = "".join(f"<th>{html.escape(HEADERS.get(str(c), str(c)))}</th>" for c in [index_label, *df.columns])
    body = []
    for idx, row in df.iterrows():
        cells = [f"<td>{html.escape(LABELS.get(idx, str(idx)))}</td>"]
        for c in df.columns:
            v = row[c]
            if isinstance(v, float) and pd.isna(v):
                cells.append("<td>–</td>")
            elif c in fmt:
                cells.append(f"<td class='num'>{format(v, fmt[c])}</td>")
            else:
                cells.append(f"<td>{html.escape(str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#f4f5f7;color:#1d2433;line-height:1.5}
main{max-width:1150px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.7rem;margin:.2em 0}h2{font-size:1.25rem;margin-top:2em;border-bottom:2px solid #d9dde3;padding-bottom:.2em}
.card{background:#fff;border-radius:8px;padding:16px;margin:16px 0;box-shadow:0 1px 2px rgba(0,0,0,.06);overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{padding:6px 10px;border-bottom:1px solid #e6e8eb;text-align:left}
th{background:#eef0f3}td.num{text-align:right;font-variant-numeric:tabular-nums}
.kpis{display:flex;flex-wrap:wrap;gap:12px}.kpi{background:#fff;border-radius:8px;padding:12px 16px;flex:1 1 180px;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.kpi b{display:block;font-size:1.4rem}.muted{color:#5b6475;font-size:.9rem}code{background:#eef0f3;padding:1px 4px;border-radius:3px}
ul.notes li{margin:.3em 0}
"""


def build_report(results_dir: Path, out_path: Path | None = None) -> Path:
    results_dir = Path(results_dir)
    out_path = Path(out_path) if out_path else results_dir / "report.html"
    summary = json.loads((results_dir / "summary.json").read_text(encoding="utf-8"))
    observed = read_multi(results_dir / "observed.csv")
    simulated = read_multi(results_dir / "simulated.csv")
    obs_c = by_carrier(observed)
    sim_c = by_carrier(simulated)
    carrier_metrics = pd.read_csv(results_dir / "carrier_metrics.csv", index_col=0)
    zone_metrics = pd.read_csv(results_dir / "zone_metrics.csv", index_col=0)
    capacity = pd.read_csv(results_dir / "capacity.csv", index_col=0)
    prices = pd.read_csv(results_dir / "prices.csv", index_col=0, parse_dates=True)
    flows = pd.read_csv(results_dir / "flows.csv", index_col=0, parse_dates=True)
    flows_summary = pd.read_csv(results_dir / "flows_summary.csv", index_col=0)

    total = carrier_metrics["observed_gwh"].sum()
    abs_err = (carrier_metrics["simulated_gwh"] - carrier_metrics["observed_gwh"]).abs().sum()
    mix_error = 100 * abs_err / (2 * total) if total else float("nan")

    cfg = summary["config"]
    metric_fmt = {"observed_gwh": ",.1f", "simulated_gwh": ",.1f", "bias_mw": ",.0f", "mae_mw": ",.0f",
                  "rmse_mw": ",.0f", "nmae": ".2f", "correlation": ".2f", "energy_error_pct": "+.1f"}

    sources_rows = "".join(
        f"<tr><td><a href='{html.escape(v['url'])}'>{html.escape(k)}</a></td>"
        f"<td><code>{v['sha256'][:16]}…</code></td><td>{html.escape(v['downloaded_utc'])}</td></tr>"
        for k, v in summary["sources"].items()
    )
    notes = "".join(f"<li>{html.escape(x)}</li>" for x in summary["notes"]) or "<li>None.</li>"
    costs = pd.DataFrame({k: v for k, v in cfg["carriers"].items()}).T
    shares = pd.DataFrame({"share": cfg["demand"]["zone_shares"]})
    links = pd.DataFrame(cfg["transmission"]["links"], columns=["from", "to", "mw"]).set_index("from")
    curtail = summary.get("model_curtailment_gwh", {})
    curtail_txt = ", ".join(f"{LABELS.get(k, k)} {v:,.1f} GWh" for k, v in curtail.items()) or "none"

    figs = [
        _stack_figure(obs_c, sim_c),
        _energy_bars(carrier_metrics),
        _carrier_lines(obs_c, sim_c),
        _price_figure(prices),
        _flow_figure(flows, flows_summary["p_nom_mw"]),
    ]
    fig_html = [_fig_html(f, i == 0) for i, f in enumerate(figs)]

    start, end = summary["period"]
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>pypsa-chile report {start[:10]} to {end[:10]}</title><style>{CSS}</style></head>
<body><main>
<p class="muted">pypsa-chile {html.escape(summary['version'])}</p>
<h1>Economic dispatch of the SEN vs observed generation</h1>
<p>Period {start[:10]} to {end[:10]} (local time, hourly). Zonal transport model with
{len(cfg['zones'])} zones, solved with HiGHS. Installed capacity from the CEN year-end {summary['capacity_year']} table.</p>
<div class="kpis">
<div class="kpi"><span class="muted">Demand (observed gross generation)</span><b>{summary['demand_gwh']:,.1f} GWh</b></div>
<div class="kpi"><span class="muted">Mix error (half the sum of |sim − obs| energy)</span><b>{mix_error:.1f}%</b></div>
<div class="kpi"><span class="muted">Unserved energy in the model</span><b>{summary['load_shedding_gwh']:,.2f} GWh</b></div>
<div class="kpi"><span class="muted">Objective</span><b>{summary['objective_usd'] / 1e6:,.1f} M USD</b></div>
</div>

<h2>Generation by technology</h2>
<div class="card">{fig_html[0]}</div>
<div class="card">{fig_html[1]}</div>
<div class="card">{_table(carrier_metrics, metric_fmt, "technology")}
<p class="muted">MAE, RMSE and bias in MW over hourly values; nMAE is MAE over the mean observed output.
Solar, wind and run-of-river use the observed output as availability, so their error only reflects
curtailment by the model. Reservoir hydro and CSP are capped at their observed energy for the period.</p></div>
<div class="card">{fig_html[2]}</div>

<h2>Zones</h2>
<div class="card">{_table(zone_metrics, metric_fmt, "zone")}
<p class="muted">Zonal generation depends on the assumed demand shares and corridor limits below,
so these numbers are a weaker test than the system-wide mix.</p></div>
<div class="card">{fig_html[3]}</div>
<div class="card">{fig_html[4]}</div>

<h2>Curtailment</h2>
<div class="card"><p>Energy the model chose not to use from profile technologies: {curtail_txt}.</p>
<p class="muted">The CEN generation file reports energy actually delivered, so observed curtailment is
already removed from the availability profiles. Real curtailment is published separately by CEN
(monthly "Reducciones de Energía" reports) and is not compared in this version.</p></div>

<h2>Inputs and assumptions</h2>
<div class="card"><h3>Installed capacity used (MW)</h3>{_table(capacity, {c: ',.0f' for c in capacity.columns}, 'zone')}</div>
<div class="card"><h3>Technologies</h3>{_table(costs, {'marginal_cost': ',.1f'}, 'carrier')}
<p class="muted">Marginal costs (USD/MWh) are assumptions that set the merit order, not CEN declared costs.
Thermal availability and must-run are taken from the {cfg['thermal_availability']['window_days']} days before the
period (maximum output, and the {cfg['thermal_availability'].get('must_run_quantile')} quantile of output).</p></div>
<div class="card"><h3>Demand shares</h3>{_table(shares, {'share': '.3f'}, 'zone')}
<h3>Corridors</h3>{_table(links, {'mw': ',.0f'}, 'from')}</div>
<div class="card"><h3>Notes from the build</h3><ul class="notes">{notes}</ul></div>
<div class="card"><h3>Data sources</h3><table><thead><tr><th>File</th><th>SHA-256</th><th>Downloaded (UTC)</th></tr></thead>
<tbody>{sources_rows}</tbody></table>
<p class="muted">Data: Coordinador Eléctrico Nacional, Reportes y Estadísticas.</p></div>
</main></body></html>
"""
    out_path.write_text(doc, encoding="utf-8")
    return out_path
