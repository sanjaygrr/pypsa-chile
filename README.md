# pypsa-chile

A small, reproducible economic dispatch model of the Chilean National Electric
System (SEN), built with [PyPSA](https://github.com/PyPSA/PyPSA) and only
public data that can be downloaded without an account. It fetches hourly
generation from the Coordinador Eléctrico Nacional (CEN), builds a zonal
network, solves a week of dispatch with HiGHS and checks the result against
what actually happened.

## Motivation

Chile has one of the fastest growing shares of solar and wind in the world,
heavy curtailment in the north and an ongoing coal phase-out. Most models of
the SEN used in planning are proprietary (PLEXOS, PLP, AMEBA) or depend on
input workbooks that are not distributed. The open
[PyPSA-CL](https://github.com/paredes-vergara/PyPSA-CL) model is detailed, but
its input data has to be obtained separately.

pypsa-chile aims at the opposite end of the trade-off: a coarse model that
anyone can rebuild from scratch with one command, where every assumption is in
one YAML file, and whose output is always compared with observed data. It is
meant as a baseline for teaching, for quick studies, and for measuring how much
each modelling assumption matters.

## What it does

1. `pypsa-chile fetch` downloads from CEN:
   - hourly gross generation of every generating unit for a calendar year, with
     region, type and subtype;
   - installed capacity by region and technology at 31 December of each year.

   The unit-level file (~100 MB per year) is read in streaming mode and
   aggregated to hour x region x technology (~5 MB). Every raw file is
   recorded in `data/raw/manifest.json` with its URL, SHA-256 and download time.
2. `pypsa-chile run` builds a four-zone network (Norte Grande, Norte Chico,
   Centro, Sur), solves the dispatch for the configured period with HiGHS and
   compares it with the observed generation: energy, bias, MAE, RMSE, nMAE and
   correlation per technology and per zone.
3. `pypsa-chile report` writes a self-contained HTML report with the charts,
   the metrics, every assumption used and the data provenance.

## Install

Python 3.10 or newer.

```bash
git clone https://github.com/sanjaygrr/pypsa-chile
cd pypsa-chile
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
```

With [uv](https://github.com/astral-sh/uv): `uv venv && uv pip install -e ".[test]"`.

## Usage

```bash
pypsa-chile fetch                 # ~100 MB download, a few minutes to parse
pypsa-chile run --report          # writes results/ and results/report.html
```

Change the period from the command line or with your own YAML file, which only
needs the keys it overrides:

```bash
pypsa-chile fetch --start 2025-06-02 --end 2025-06-08
pypsa-chile run --start 2025-06-02 --end 2025-06-08 -o results/june --report
pypsa-chile run -c my_assumptions.yaml -o results/test
```

A one-week run uses well under 1 GB of memory and solves in a few seconds.
Years currently configured: 2024 and 2025. New years are added under
`sources.generation_by_unit` once CEN publishes the file.

## Model

| Element | Representation | Source |
|---|---|---|
| Zones | 4 buses; regions assigned in `zones` | assumption |
| Demand | Hourly system demand = observed gross generation; split by fixed zonal shares | CEN generation file; shares partly assumed (see below) |
| Solar, wind, run-of-river | Available power = observed output; the model may curtail | CEN generation file |
| Reservoir hydro, CSP | Dispatchable, energy over the period capped at the observed energy | CEN generation file |
| Hydro capacity | One installed capacity per zone shared by run-of-river and reservoir | CEN capacity file |
| Thermal and geothermal | Capacity from CEN; availability = max output in the 28 days before the period over capacity; must-run = 5 % quantile of that output | CEN files |
| Merit order | Constant marginal cost per technology | assumption |
| Transmission | Transport model between adjacent zones, lossless, fixed limits | assumption |
| Unserved energy | Generator per zone at 3,000 USD/MWh | assumption |

Thermal availability and must-run use only data from before the simulated
period, so the comparison is out of sample for thermal plants.

### Assumptions to be aware of

All of them are in [`src/pypsa_chile/data/default.yaml`](src/pypsa_chile/data/default.yaml).

- **Demand is gross generation.** No hourly demand series is published without
  credentials, so demand is set to the total observed gross generation. This
  includes transmission losses and auxiliary consumption, and makes total
  generation match by construction. The test is therefore on *which*
  technologies serve the load, not on how much is served.
- **Zonal demand shares.** The Norte Grande share (0.252) is the 2016 sales of
  the former SING over total sales in CEN's sales history file, the last year
  both systems were reported separately. The split between Norte Chico, Centro
  and Sur is an assumption.
- **Corridor limits** (3,000 / 3,000 / 6,000 MW) are round numbers, not
  derived from the CEN transmission database.
- **Marginal costs** only set the order coal < gas < other thermal < diesel.
  They are not CEN's declared variable costs.
- **Clock time.** The CEN file has 24 hourly values per day; the extra and
  missing hours on daylight-saving change days cannot be recovered.

## Results for 2025-10-06 to 2025-10-12

Default configuration, CEN data downloaded on 2026-10-30. Observed totals
were checked against an independent sum of the raw workbook.

| Technology | Observed (GWh) | Simulated (GWh) | MAE (MW) | RMSE (MW) | nMAE |
|---|---:|---:|---:|---:|---:|
| Solar PV | 438.3 | 438.3 | 0 | 0 | 0.00 |
| Wind | 260.7 | 260.7 | 0 | 0 | 0.00 |
| Coal | 258.5 | 395.1 | 880 | 969 | 0.57 |
| Hydro, reservoir | 241.9 | 241.9 | 576 | 723 | 0.40 |
| Hydro, run-of-river | 197.8 | 197.8 | 0 | 0 | 0.00 |
| Natural gas | 127.9 | 0.3 | 760 | 854 | 1.00 |
| Other thermal | 50.6 | 41.6 | 55 | 66 | 0.18 |
| Geothermal | 2.2 | 2.8 | 3 | 3 | 0.25 |
| Diesel | 0.8 | 0.3 | 3 | 9 | 0.63 |

Total demand 1,578.8 GWh, no unserved energy. Solar, wind and run-of-river
match exactly because their observed output is the availability and the
model curtailed nothing in this week. The main finding is that a cost-only
merit order with coal cheaper than gas replaces almost all gas with coal; in
reality about 760 MW of gas ran on average. Reservoir hydro has the right
energy but too sharp a daily shape: the model pushes it almost entirely into
the hours without sun, while the observed output keeps 450-550 MW at midday.

These numbers describe this model with these assumptions, not the SEN.

## Limitations

- Battery storage is not in either CEN source file and is not modelled.
- No unit commitment, ramping limits, reserves or start-up costs.
- Hydro is not linked to inflows or reservoir levels; the observed energy of
  the week is used as a budget.
- The CEN generation file lists the Cerro Dominador CSP plant under
  "Solar/Solar", so its output is counted as solar PV and the CSP carrier is
  empty.
- Observed curtailment is not compared. CEN publishes it in the monthly
  "Reducciones de Energía" workbooks, which have irregular file names.
- Raw-file URLs change when CEN publishes a new edition and must be updated in
  the config. The CEN web pages are behind a bot challenge, but the files
  themselves download directly.
- Capacity is regional and year-end; units commissioned during the year can
  make observed output exceed it. The build reports these cases and raises the
  capacity to the observed peak.

## Data sources

Used:

- CEN, Reportes y Estadísticas, hourly generation per unit:
  [2025](https://www.coordinador.cl/wp-content/uploads/2026/05/CEN-hist_gen_de_energia_por_central_2025.xlsx),
  [2024](https://www.coordinador.cl/wp-content/uploads/2025/04/CEN-hist_gen_de_energia_por_central_2024.xlsx).
- CEN, [installed capacity by region and technology](https://www.coordinador.cl/wp-content/uploads/2026/05/CEN-hist_cap_inst_por_region_y_tecno.xlsx).
- CEN, [energy sales history](https://www.coordinador.cl/wp-content/uploads/2026/05/CEN-hist_ventas_de_energia.xlsx) (for the Norte Grande demand share; read by hand, not by the code).

Possible future sources:

- CEN SIP public API (`sipub.api.coordinador.cl`): hourly demand, generation,
  marginal costs. Requires a free `user_key` from
  [portal.api.coordinador.cl](https://portal.api.coordinador.cl).
- CEN [Infotecnica API](https://api-infotecnica.coordinador.cl/) (no key):
  plants, substations and line ratings, useful for deriving corridor limits.
- CNE [Energía Abierta](https://energiaabierta.cl/) and
  [datos.gob.cl](https://datos.gob.cl/organization/comision-nacional-de-energia):
  monthly generation and capacity.

## Related work

- [PyPSA-CL](https://github.com/paredes-vergara/PyPSA-CL): detailed PyPSA model
  of the SEN (expansion planning, unit commitment, dispatch); input data not
  distributed with the code.
- [PyPSA-Earth](https://github.com/pypsa-meets-earth/pypsa-earth): global
  open model that can be built for Chile from global datasets.
- [PyPSA model catalogue](https://docs.pypsa.org/latest/home/models/).
- Reyes Cerda and Cea Morales (2026), plant-level curtailment dataset of the
  SEN, [doi:10.5281/zenodo.21198816](https://doi.org/10.5281/zenodo.21198816),
  code at [curtailmentiq-research](https://github.com/Pablosebastian-reyes/curtailmentiq-research).

## Development

```bash
pytest
```

Tests use small excerpts of the real CEN files in `tests/fixtures` and never
touch the network. `tests/fixtures/make_fixtures.py` rebuilds them after a
fetch.

## License

MIT. Data belongs to the Coordinador Eléctrico Nacional; check its terms before
redistributing raw files.
