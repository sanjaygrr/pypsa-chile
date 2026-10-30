# pypsa-chile

A small, reproducible economic dispatch model of the Chilean National Electric
System (SEN), built with [PyPSA](https://github.com/PyPSA/PyPSA) from public
files that download without an account. It fetches hourly generation from the
Coordinador Eléctrico Nacional (CEN), builds a zonal network, solves a week of
dispatch with HiGHS and backtests the thermal and hydro dispatch against the
observed generation of the same week.

## Motivation

The SEN combines a large and growing share of solar and wind in the north,
reservoir hydro in the south and a thermal fleet in transition away from coal.
The models used for planning and operation (PLEXOS, PLP, AMEBA) are
proprietary, and the open [PyPSA-CL](https://github.com/paredes-vergara/PyPSA-CL)
model depends on input workbooks that are not distributed with its code.

pypsa-chile sits at the other end of the trade-off: a coarse model that anyone
can rebuild from scratch with two commands, with every assumption in one YAML
file and every run compared with observed data. It is meant as a transparent
baseline: for teaching, for quick studies, and for measuring how much each
modelling assumption explains of the real dispatch.

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
   compares it with the observed generation per technology and per zone.
3. `pypsa-chile report` writes a self-contained HTML report with charts,
   metrics, the assumptions used and the provenance of each input file.

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

Change the period from the command line, or pass a YAML file that only lists
the keys it overrides:

```bash
pypsa-chile fetch --start 2025-01-13 --end 2025-01-19   # also needs 2024 for the look-back
pypsa-chile run --start 2025-01-13 --end 2025-01-19 -o results/2025-01 --report
pypsa-chile run -c my_assumptions.yaml -o results/test
```

A one-week run peaks at about 300 MB of memory and solves in seconds.
Configured years: 2024 and 2025 (CEN changed the file layout between the two
editions; both are supported). New years go under `sources.generation_by_unit`
once CEN publishes them.

## Model

| Element | Representation | Source |
|---|---|---|
| Zones | 4 buses; CEN regions assigned in `zones` | assumption |
| Demand | Hourly system demand = observed gross generation, split by fixed zonal shares | CEN generation file; shares partly assumed |
| Solar, wind, run-of-river | Available power = observed output; the model may curtail | CEN generation file |
| Reservoir hydro, CSP | Dispatchable; energy over the period capped at the observed energy | CEN generation file |
| Hydro capacity | One installed capacity per zone, shared by run-of-river and reservoir | CEN capacity file |
| Thermal and geothermal | Capacity from CEN; availability = maximum output in the 28 days before the period over capacity; minimum output = 5 % quantile of that output | CEN files |
| Merit order | Constant marginal cost per technology | assumption |
| Transmission | Transport model between adjacent zones, lossless, fixed limits | assumption |
| Unserved energy | One generator per zone at 3,000 USD/MWh | assumption |

### What the comparison tests, and what it does not

This is a backtest conditioned on the observed week. Total demand equals
observed generation, solar, wind and run-of-river can only use what they
actually produced, and reservoir hydro is given its observed weekly energy.
Their errors are zero or near zero by construction and are shown only for
completeness. What the model has to get right on its own is:

- how the residual load is shared between coal, gas, other thermal and diesel;
- when reservoir hydro is used within the week;
- zonal balances and flows (weakly, since zonal demand is assumed).

Thermal availability and minimum output use only data from before the
simulated period. Everything else comes from the simulated week itself.

### Assumptions to be aware of

All of them are in [`src/pypsa_chile/data/default.yaml`](src/pypsa_chile/data/default.yaml).

- **Demand is gross generation.** v0.1 uses only sources that need no key, and
  none of them publishes hourly demand. Gross generation includes transmission
  losses and auxiliary consumption.
- **Zonal demand.** The Norte Grande share (0.25) is the 2016 sales of the
  former SING over total sales in CEN's sales history file, the last year both
  systems were reported separately. Sales are annual energy, not coincident
  demand, and northern mining load has grown since. The split between Norte
  Chico, Centro and Sur is an assumption, and every zone gets the national
  hourly shape.
- **Corridor limits** (3,000 / 3,000 / 6,000 MW) are round numbers, not
  derived from the CEN transmission database, and are likely looser than the
  real post-contingency limits that cause curtailment in the north. With these
  limits the model curtails nothing in the weeks tested.
- **Marginal costs** only set the order coal < gas < other thermal < diesel.
  They are not CEN's declared variable costs.
- **Minimum output** (5 % quantile of recent output) is a heuristic stand-in
  for cogeneration, take-or-pay fuel contracts, minimum stable load and
  security constraints, none of which are published per hour. Set
  `must_run_quantile: null` to switch it off.
- **Clock time.** The CEN files have 24 hourly values per day (the 2024 edition
  adds a 25th column on the day daylight saving time ends, 8.8 GWh in 2024,
  which is left out and logged).

## Results

Default configuration, CEN files downloaded on 2026-10-30. Observed weekly
totals per type were checked with a separate script that sums the hour columns
of the raw workbook directly. MAE and RMSE are over hourly values in MW; nMAE
is MAE over mean observed output.

**2025-10-06 to 2025-10-12** (demand 1,578.8 GWh, no unserved energy)

| Technology | Observed (GWh) | Simulated (GWh) | MAE (MW) | RMSE (MW) | nMAE |
|---|---:|---:|---:|---:|---:|
| Coal | 258.5 | 395.1 | 880 | 969 | 0.57 |
| Natural gas | 127.9 | 0.3 | 760 | 854 | 1.00 |
| Hydro, reservoir | 241.9 | 241.9 | 575 | 723 | 0.40 |
| Other thermal | 50.6 | 41.6 | 55 | 66 | 0.18 |
| Diesel | 0.8 | 0.3 | 3 | 9 | 0.63 |
| Geothermal | 2.2 | 2.8 | 3 | 3 | 0.25 |
| Solar, wind, run-of-river | 896.8 | 896.8 | 0 | 0 | 0.00 (by construction) |

**2025-01-13 to 2025-01-19** (demand 1,653.9 GWh, no unserved energy)

| Technology | Observed (GWh) | Simulated (GWh) | MAE (MW) | RMSE (MW) | nMAE |
|---|---:|---:|---:|---:|---:|
| Coal | 142.3 | 361.8 | 1,307 | 1,342 | 1.54 |
| Natural gas | 262.4 | 60.0 | 1,245 | 1,461 | 0.80 |
| Hydro, reservoir | 210.6 | 210.6 | 810 | 923 | 0.65 |
| Other thermal | 48.5 | 33.3 | 90 | 97 | 0.31 |
| Diesel | 3.2 | 0.3 | 18 | 30 | 0.91 |
| Geothermal | 2.8 | 3.8 | 6 | 6 | 0.35 |
| Solar, wind, run-of-river | 984.0 | 984.0 | 0 | 0 | 0.00 (by construction) |

What these runs show:

- **Thermal mix.** A merit order based on cost alone does not reproduce the
  observed coexistence of coal and gas. With coal cheaper than gas (default)
  the model replaces almost all gas with coal; in the October week, making gas
  cheaper than coal (55 USD/MWh) flips the error (coal 106.5 GWh, gas
  289.0 GWh). The gas that runs in reality is likely held on by constraints not
  in the model: unit commitment and minimum stable load, security constraints
  in the north, reserves and fuel contracts.
- **Minimum output.** Switching it off (October week) leaves other thermal at
  zero against 50.6 GWh observed and raises the mix distance from 8.7 % to
  11.4 %.
- **Reservoir hydro** has the right energy by construction but too sharp a
  daily shape: the model pushes it almost entirely into the hours without sun,
  while observed output stays at 440-540 MW at midday. Part of this comes from
  sharing one capacity with run-of-river, and from the absence of irrigation
  agreements, ecological flows and cascade constraints.

These numbers describe this model with these assumptions, not the SEN.

## Limitations

- Battery storage is not modelled. The 2024 file reports battery discharge
  (1.07 TWh in 2024), which is taken as a fixed observed profile; the 2025 file
  has no battery category.
- No unit commitment, ramping limits, reserves, start-up costs or losses.
- Hydro is not linked to inflows or reservoir levels; the observed energy of
  the week is used as a budget.
- The CEN generation file lists the Cerro Dominador CSP plant under
  "Solar/Solar", so its output is counted as solar PV and the CSP carrier is
  empty.
- Observed curtailment is not compared. CEN publishes it in the monthly
  "Reducciones de Energía" workbooks, which have irregular file names.
- Regions outside the four zones (Magallanes appears in the files) are left out
  of demand and of the comparison; the energy involved is reported.
- Capacity is regional and year-end. Units commissioned during the year can
  make observed output exceed it; the model then raises the capacity to the
  observed peak and the report lists each case.
- Raw-file URLs change when CEN publishes a new edition and must be updated in
  the config. The CEN web pages are behind a bot challenge, but the files
  themselves download directly.

## Data sources

Used by the code:

- CEN, Reportes y Estadísticas, hourly generation per unit:
  [2025](https://www.coordinador.cl/wp-content/uploads/2026/05/CEN-hist_gen_de_energia_por_central_2025.xlsx),
  [2024](https://www.coordinador.cl/wp-content/uploads/2025/04/CEN-hist_gen_de_energia_por_central_2024.xlsx).
- CEN, [installed capacity by region and technology](https://www.coordinador.cl/wp-content/uploads/2026/05/CEN-hist_cap_inst_por_region_y_tecno.xlsx).

Used for one config value (read by hand):

- CEN, [energy sales history](https://www.coordinador.cl/wp-content/uploads/2026/05/CEN-hist_ventas_de_energia.xlsx).

Candidates for later versions:

- CEN SIP public API (`sipub.api.coordinador.cl`): hourly demand, generation
  and marginal costs. Requires a free `user_key` from
  [portal.api.coordinador.cl](https://portal.api.coordinador.cl).
- CEN [Infotecnica API](https://api-infotecnica.coordinador.cl/) (no key):
  plants, substations and circuit ratings, to derive corridor limits.
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

MIT for the code. The data belongs to the Coordinador Eléctrico Nacional; check
its terms before redistributing raw files.
