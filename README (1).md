# Real Exchange Rate Explorer

A small Streamlit app that pulls **monthly CPI and exchange-rate data from the IMF**, computes the **real exchange rate (RER)** between any two IMF countries (or the Euro area), and lets you explore it in interactive charts and download the underlying numbers as CSV.

Compatible with **Python 3.12**.

## Quick start

```bash
python3.12 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at <http://localhost:8501>. It needs internet access to `api.imf.org`.

## How to use it

1. Pick **Country 1** and **Country 2** (IMF countries plus the Euro area, code `G163`). Defaults: United States vs Euro area.
2. Choose the **sample period** (start and end month) with the range slider. Everything is recomputed when you move it.
3. Choose the chart: **Real** (Real Index), **Nominal** (S), or **Both** (Real on the left axis, Nominal in its actual currency units on the right axis). Charts support zoom, pan and hover.
4. Click **Download CSV** to get every month in the selected sample with all inputs and calculations.

## Method

| Symbol | Meaning |
|---|---|
| `S(t)` | Units of Country 2 currency per 1 unit of Country 1 currency |
| `P1(t)`, `P2(t)` | Monthly CPI (all items, index) of Country 1 and Country 2 |
| `RER(t)` | `S(t) × P1(t) / P2(t)` |
| `RER*` | Average of `RER(t)` over the **valid months** of the selected sample |
| Real Index(t) | `100 × RER(t) / RER*` (averages exactly 100 over the sample) |

- **Exchange-rate direction.** The IMF publishes local-currency units per US dollar (`E`). The app converts: `S(t) = E2(t) / E1(t)`. The US dollar is the numeraire (`E = 1`), so no exchange-rate request is made for the United States.
- **Valid month.** A month is valid only if `S`, `P1` and `P2` are all available and positive. `RER*` is computed over valid months only, and is **recomputed whenever the start or end month changes**.
- **Gaps.** Nothing is interpolated or filled. Invalid months stay in the table and CSV (blank `RER`/`Real_Index`) and appear as gaps in the chart.
- **Nominal S is never normalized.** It is plotted in actual currency units, wherever it is available in the sample.
- **Reading the Real Index.** A rise means Country 1's prices have risen relative to Country 2's when measured in a common currency, that is, a real appreciation of Country 1's currency against Country 2's.
- **Data are used from the time they are available.** The selectable period runs from the first to the last month in which `S`, `P1` and `P2` are all available (never earlier than January 1976). For example, an economy whose CPI starts in 2002 is analysed and plotted from 2002. The page states the available range and which series sets the start.

## Data source

IMF SDMX 3.0 API, base URL `https://api.imf.org/external/sdmx/3.0`, requested as JSON from January 1976 onward:

| Data | Request path | Key |
|---|---|---|
| Monthly CPI | `data/dataflow/IMF.STA/CPI/+/{key}` | `{ISO3}.CPI._T.IX.M`, or `{code}.HICP._T.IX.M` if there is no `CPI`-type series (see below) |
| Exchange rate (local currency per USD, period average) | `data/dataflow/IMF.STA/ER/+/{key}` | `{ISO3}.XDC_USD.PA_RT.M` |
| Country list | `structure/codelist/IMF/CL_COUNTRY/+` | – |

- **CPI vs HICP.** The IMF's CPI dataflow has an `INDEX_TYPE` dimension. The app asks for `CPI` first and, if the IMF has no such series for that economy, for `HICP` (Eurostat's harmonised index, which is how the Euro area aggregate is covered). The index type actually used is shown on the page, in the coverage table and in the CSV.
- The Euro area uses the code `G163`. The country list keeps ISO3-style codes plus `G163`. If the IMF codelist cannot be downloaded, a built-in list is used and the app says so.
- Downloads are cached for 6 hours (country list: 24 hours). The sidebar button **Refresh IMF data** clears the cache.
- Requests are spaced at least 1 second apart, and transient errors (HTTP 429/5xx, network errors) are retried with back-off.
- The expander **Data sources, requests and coverage** at the bottom of the page shows the exact URLs called and the first/last month and number of observations of each of the four series.

## CSV columns

One row per month in the selected sample (including months with missing data). File name: `rer_{country1}_{country2}_{start}_{end}.csv`.

| Column | Description |
|---|---|
| `month` | `YYYY-MM` |
| `country1`, `country2` | IMF codes of the selected countries |
| `P1_cpi`, `P2_cpi` | Price index of Country 1 / Country 2 (IMF base year of each series) |
| `P1_index_type`, `P2_index_type` | Which IMF index was used: `CPI` or `HICP` |
| `E1_per_usd`, `E2_per_usd` | Local currency units per USD (IMF); `1.0` for the United States |
| `S_nominal` | `E2 / E1`, units of Country 2 currency per unit of Country 1 currency |
| `RER` | `S × P1 / P2` (blank if the month is not valid) |
| `RER_star` | Average RER over the valid months of the sample (same value on every row) |
| `Real_Index` | `100 × RER / RER_star` |
| `valid_month` | `1` if `S`, `P1`, `P2` were all available, else `0` |

## Limitations and notes

- **IMF coverage varies.** Some countries have no monthly CPI or no period-average exchange rate, or have short or patchy histories. The app then names the missing series and asks for a different selection. The country list may include a few non-country aggregates that have no data.
- **Currency changes are not spliced.** `S(t)` is whatever currency unit the IMF reports. If a country changed or redenominated its currency (for example at euro adoption), check the series around that date for a break.
- **Euro area.** Its price index is the IMF's `HICP` series and its exchange rate must exist under `G163` in the IMF exchange-rate dataset; if either is missing, the app reports it. When one side of a pair uses `CPI` and the other `HICP`, the two are different (but both consumer-price) indices; the page notes which one is used.
- CPI base years differ across countries. This does not affect the Real Index, because it is divided by its own sample average, but it does change the level of `RER` and `RER*`.

## Configuration (optional environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `IMF_API_BASE_URL` | `https://api.imf.org/external/sdmx/3.0` | Point the app at another SDMX 3.0 endpoint or a test server |
| `IMF_MIN_INTERVAL_SECONDS` | `1.0` | Minimum spacing between IMF requests |

## Troubleshooting

- **"Could not retrieve data from the IMF"**: the message includes the failing URL and HTTP status. Check connectivity with
  `curl -H "Accept: application/json" "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/CPI/+/USA.CPI._T.IX.M?dimensionAtObservation=TIME_PERIOD"`
  and retry later if the API is rate-limiting you.
- **"The IMF returned no monthly data … for: …"**: that series does not exist for the chosen country (see Limitations). For a price index the message lists the index types tried (`CPI`, `HICP`) and, if the IMF publishes the economy only under some other index type, which one. Try another country.
- **Stale data**: use **Refresh IMF data** in the sidebar.

## Verification status

The app was tested on Python 3.12 with unit tests (parsing, RER arithmetic against hand-computed values, chart axes), Streamlit `AppTest` runs of every widget path, and a real-browser run (charts, slider, country selection, CSV download checked against an independent calculation). Those tests used a **mock IMF server** that reproduces the SDMX-JSON response structure of the API; the live `api.imf.org` could not be reached from the development sandbox. On your first live run, check that the default pair (United States / Euro area) loads, and that the *Data sources, requests and coverage* expander shows sensible first and last months (1976 or later, up to a recent month) for all series.
