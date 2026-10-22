"""Real Exchange Rate (RER) Explorer: a Streamlit app built on monthly IMF data.

Definitions
-----------
S(t)        units of Country 2 currency per one unit of Country 1 currency
P1(t), P2(t)  monthly CPI of Country 1 and Country 2
RER(t)      = S(t) * P1(t) / P2(t)
RER*        = average of RER(t) over the valid months of the selected sample
Real Index  = 100 * RER(t) / RER*

The IMF publishes exchange rates as local-currency units per US dollar (E_i), so
S(t) = E_2(t) / E_1(t).  The US dollar itself is the numeraire (E = 1).

Run with:  streamlit run app.py
"""

from __future__ import annotations

import math
import os
import re
import threading
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# Base URL can be overridden (used by the automated tests to point at a mock server).
IMF_BASE_URL = os.environ.get("IMF_API_BASE_URL", "https://api.imf.org/external/sdmx/3.0").rstrip("/")
# Minimum spacing between two requests to the IMF API (be polite; avoids rate limiting).
MIN_REQUEST_INTERVAL = _env_float("IMF_MIN_INTERVAL_SECONDS", 1.0)

REQUEST_TIMEOUT = 60  # seconds
MAX_RETRIES = 3
CACHE_TTL_SECONDS = 6 * 3600
REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "real-exchange-rate-explorer (Streamlit)",
}

# SDMX dataflows (agency, id) and series keys, as given in the project specification.
DATA_AGENCIES = ("IMF.STA", "all")  # "all" is only a fallback if IMF.STA answers 404
CPI_FLOW = "CPI"
FX_FLOW = "ER"
CPI_KEY = "{iso}.CPI._T.IX.M"  # monthly CPI index, all items
FX_KEY = "{iso}.XDC_USD.PA_RT.M"  # local currency per USD, period average, monthly

EURO_AREA = "G163"
USD = "USA"  # the US dollar is the numeraire of the IMF exchange-rate series
SAMPLE_START = pd.Timestamp("1976-01-01")
SAMPLE_START_SDMX = "1976-M01"

REAL_COLOR = "#1f77b4"
NOMINAL_COLOR = "#d95f02"

# Used only if the IMF country codelist cannot be downloaded.
FALLBACK_COUNTRIES_RAW = """
AFG|Afghanistan;ALB|Albania;DZA|Algeria;AGO|Angola;ATG|Antigua and Barbuda;ARG|Argentina;
ARM|Armenia;ABW|Aruba;AUS|Australia;AUT|Austria;AZE|Azerbaijan;BHS|Bahamas, The;BHR|Bahrain;
BGD|Bangladesh;BRB|Barbados;BLR|Belarus;BEL|Belgium;BLZ|Belize;BEN|Benin;BTN|Bhutan;
BOL|Bolivia;BIH|Bosnia and Herzegovina;BWA|Botswana;BRA|Brazil;BRN|Brunei Darussalam;
BGR|Bulgaria;BFA|Burkina Faso;BDI|Burundi;CPV|Cabo Verde;KHM|Cambodia;CMR|Cameroon;CAN|Canada;
CAF|Central African Republic;TCD|Chad;CHL|Chile;CHN|China;COL|Colombia;COM|Comoros;
COD|Congo, Democratic Republic of the;COG|Congo, Republic of;CRI|Costa Rica;CIV|Côte d'Ivoire;
HRV|Croatia;CYP|Cyprus;CZE|Czech Republic;DNK|Denmark;DJI|Djibouti;DMA|Dominica;
DOM|Dominican Republic;ECU|Ecuador;EGY|Egypt;SLV|El Salvador;GNQ|Equatorial Guinea;ERI|Eritrea;
EST|Estonia;SWZ|Eswatini;ETH|Ethiopia;FJI|Fiji;FIN|Finland;FRA|France;GAB|Gabon;GMB|Gambia, The;
GEO|Georgia;DEU|Germany;GHA|Ghana;GRC|Greece;GRD|Grenada;GTM|Guatemala;GIN|Guinea;
GNB|Guinea-Bissau;GUY|Guyana;HTI|Haiti;HND|Honduras;HKG|Hong Kong SAR;HUN|Hungary;ISL|Iceland;
IND|India;IDN|Indonesia;IRN|Iran;IRQ|Iraq;IRL|Ireland;ISR|Israel;ITA|Italy;JAM|Jamaica;
JPN|Japan;JOR|Jordan;KAZ|Kazakhstan;KEN|Kenya;KIR|Kiribati;KOR|Korea, Republic of;XKX|Kosovo;
KWT|Kuwait;KGZ|Kyrgyz Republic;LAO|Lao P.D.R.;LVA|Latvia;LBN|Lebanon;LSO|Lesotho;LBR|Liberia;
LBY|Libya;LTU|Lithuania;LUX|Luxembourg;MAC|Macao SAR;MDG|Madagascar;MWI|Malawi;MYS|Malaysia;
MDV|Maldives;MLI|Mali;MLT|Malta;MHL|Marshall Islands;MRT|Mauritania;MUS|Mauritius;MEX|Mexico;
FSM|Micronesia;MDA|Moldova;MNG|Mongolia;MNE|Montenegro;MAR|Morocco;MOZ|Mozambique;MMR|Myanmar;
NAM|Namibia;NRU|Nauru;NPL|Nepal;NLD|Netherlands;NZL|New Zealand;NIC|Nicaragua;NER|Niger;
NGA|Nigeria;MKD|North Macedonia;NOR|Norway;OMN|Oman;PAK|Pakistan;PLW|Palau;PAN|Panama;
PNG|Papua New Guinea;PRY|Paraguay;PER|Peru;PHL|Philippines;POL|Poland;PRT|Portugal;
PRI|Puerto Rico;QAT|Qatar;ROU|Romania;RUS|Russian Federation;RWA|Rwanda;WSM|Samoa;
SMR|San Marino;STP|São Tomé and Príncipe;SAU|Saudi Arabia;SEN|Senegal;SRB|Serbia;SYC|Seychelles;
SLE|Sierra Leone;SGP|Singapore;SVK|Slovak Republic;SVN|Slovenia;SLB|Solomon Islands;SOM|Somalia;
ZAF|South Africa;SSD|South Sudan;ESP|Spain;LKA|Sri Lanka;KNA|St. Kitts and Nevis;LCA|St. Lucia;
VCT|St. Vincent and the Grenadines;SDN|Sudan;SUR|Suriname;SWE|Sweden;CHE|Switzerland;SYR|Syria;
TWN|Taiwan Province of China;TJK|Tajikistan;TZA|Tanzania;THA|Thailand;TLS|Timor-Leste;TGO|Togo;
TON|Tonga;TTO|Trinidad and Tobago;TUN|Tunisia;TUR|Türkiye;TKM|Turkmenistan;TUV|Tuvalu;
UGA|Uganda;UKR|Ukraine;ARE|United Arab Emirates;GBR|United Kingdom;USA|United States;
URY|Uruguay;UZB|Uzbekistan;VUT|Vanuatu;VEN|Venezuela;VNM|Vietnam;PSE|West Bank and Gaza;
YEM|Yemen;ZMB|Zambia;ZWE|Zimbabwe;CUW|Curaçao;SXM|Sint Maarten
"""
FALLBACK_COUNTRIES: dict[str, str] = {
    code.strip(): name.strip()
    for code, name in (item.split("|", 1) for item in FALLBACK_COUNTRIES_RAW.replace("\n", "").split(";") if "|" in item)
}
FALLBACK_COUNTRIES[EURO_AREA] = "Euro area"

# --------------------------------------------------------------------------- #
# IMF API access
# --------------------------------------------------------------------------- #


class IMFError(RuntimeError):
    """Raised when the IMF API cannot be reached or returns an unusable answer."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class _SharedState:
    """Process-wide state shared by every user session and every script rerun.

    Streamlit re-executes this file on each interaction, so plain module-level variables
    would be reset each time; ``st.cache_resource`` keeps one instance alive instead.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_request_at = 0.0  # time.monotonic() of the latest IMF request
        self.codelist_retry_after = 0.0  # do not retry a failing country-list download before this time


@st.cache_resource
def _shared() -> _SharedState:
    return _SharedState()


def _wait_for_turn() -> None:
    """Space requests at least MIN_REQUEST_INTERVAL apart (shared by all user sessions)."""
    shared = _shared()
    with shared.lock:
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - shared.last_request_at)
        if wait > 0:
            time.sleep(wait)
        shared.last_request_at = time.monotonic()


def _api_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get("message"):
            return str(body["message"])
    except ValueError:
        pass
    return resp.reason or "HTTP error"


def http_get_json(path: str, params: dict | None = None, retries: int = MAX_RETRIES) -> tuple[dict | None, str]:
    """GET ``IMF_BASE_URL/path``.

    Returns ``(payload, url)``. ``payload`` is ``None`` when the API answers 404 (no such
    data or structure). Transient failures (network errors, 429, 5xx) are retried with a
    back-off; anything else raises ``IMFError``.
    """
    url = f"{IMF_BASE_URL}/{path.lstrip('/')}"
    shown_url = requests.Request("GET", url, params=params).prepare().url or url
    problem, status = "unknown error", None
    for attempt in range(retries):
        delay = 2.0 * (2**attempt)
        _wait_for_turn()
        try:
            resp = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            problem, status = f"network error: {exc.__class__.__name__}", None
        else:
            status = resp.status_code
            if status == 404:
                return None, shown_url
            if status < 400:
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise IMFError("The IMF API returned a response that is not valid JSON.", status) from exc
                if not isinstance(payload, dict):
                    raise IMFError("The IMF API returned an unexpected JSON structure.", status)
                return payload, shown_url
            problem = f"HTTP {status}: {_api_message(resp)}"
            if status not in (429, 500, 502, 503, 504):
                raise IMFError(f"IMF API request failed ({problem}).\nURL: {shown_url}", status)
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = float(retry_after)
        if attempt < retries - 1:
            time.sleep(min(delay, 30.0))
    raise IMFError(f"IMF API request failed after {retries} attempt(s) ({problem}).\nURL: {shown_url}", status)


def _text(value) -> str:
    """Return a plain string from an SDMX-JSON text field (str, list, or {lang: text})."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _text(value.get("en") or next(iter(value.values()), ""))
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    return ""


# ---- parsing --------------------------------------------------------------- #

_MONTHLY_PERIOD = re.compile(r"^(\d{4})-(?:M)?(\d{2})$")


def _month_start(label: str) -> pd.Timestamp | None:
    """'1976-M01' (or '1976-01') -> Timestamp('1976-01-01'); other frequencies -> None."""
    match = _MONTHLY_PERIOD.match(label.strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return pd.Timestamp(year=year, month=month, day=1)


def parse_series(payload: dict | None) -> pd.Series:
    """Turn an SDMX-JSON data message (one series, time at observation level) into a monthly Series.

    Observations are stored under compact index keys: each observation key indexes into the
    TIME_PERIOD dimension's list of values. Non-monthly periods and missing / non-numeric
    values are dropped; nothing is interpolated.
    """
    empty = pd.Series(dtype="float64")
    data = (payload or {}).get("data") or {}
    data_sets = data.get("dataSets") or []
    structures = data.get("structures") or []
    if not data_sets or not structures:
        return empty

    dims = (structures[0].get("dimensions") or {}).get("observation") or []
    time_dim = next((d for d in dims if d.get("id") == "TIME_PERIOD"), dims[0] if dims else None)
    if not time_dim:
        return empty
    periods = []
    for entry in time_dim.get("values") or []:
        label = entry if isinstance(entry, str) else (entry.get("value") or entry.get("id") or entry.get("name") or "")
        periods.append(str(label))

    measures = (structures[0].get("measures") or {}).get("observation") or []
    value_pos = next((i for i, m in enumerate(measures) if m.get("id") == "OBS_VALUE"), 0)

    # A key such as "USA.CPI._T.IX.M" identifies exactly one series; use the first with data.
    for series in (data_sets[0].get("series") or {}).values():
        observations = series.get("observations") or {}
        if not observations:
            continue
        values: dict[pd.Timestamp, float] = {}
        for index, obs in observations.items():
            try:
                period = periods[int(index)]
                raw = obs[value_pos]
                number = float(raw)
            except (IndexError, ValueError, TypeError):
                continue
            month = _month_start(period)
            if month is not None and math.isfinite(number) and month >= SAMPLE_START:
                values[month] = number
        if values:
            return pd.Series(values, dtype="float64").sort_index()
    return empty


def parse_country_codelist(payload: dict | None) -> dict[str, str]:
    """Extract {ISO3 code: name} (plus the Euro area) from an SDMX-JSON codelist message."""
    codelists = ((payload or {}).get("data") or {}).get("codelists") or []
    codes = (codelists[0].get("codes") or []) if codelists else []
    countries: dict[str, str] = {}
    for item in codes:
        code = str(item.get("id") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{3}", code):  # ISO3-style country codes; skips aggregates like G001
            countries[code] = _text(item.get("name")).strip() or code
    countries[EURO_AREA] = "Euro area"
    return countries


# ---- cached fetchers -------------------------------------------------------- #


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_series(flow: str, key: str) -> tuple[pd.Series, str]:
    """Download one monthly series. Returns (series, request URL); the series is empty if the IMF has no data."""
    base_params = {"dimensionAtObservation": "TIME_PERIOD", "attributes": "dsd", "measures": "all"}
    url = ""
    for agency in DATA_AGENCIES:
        path = f"data/dataflow/{agency}/{flow}/+/{key}"
        # First try with the server-side time filter; if the API rejects it (HTTP 400), retry without.
        for use_time_filter in (True, False):
            params = dict(base_params)
            if use_time_filter:
                params["c[TIME_PERIOD]"] = f"ge:{SAMPLE_START_SDMX}"
            try:
                payload, url = http_get_json(path, params)
            except IMFError as exc:
                if use_time_filter and exc.status == 400:
                    continue
                raise
            if payload is not None:
                return parse_series(payload), url
            break  # 404 -> try the next agency scope
    return pd.Series(dtype="float64"), url


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_country_codelist() -> dict[str, str]:
    """Download the IMF country codelist (raises IMFError if it cannot be obtained)."""
    last_error = "codelist not found"
    for path in (
        "structure/codelist/IMF/CL_COUNTRY/+",
        "structure/codelist/all/CL_COUNTRY/+",
        "structure/codelist/IMF.STA/CL_COUNTRY/+",
    ):
        try:
            payload, _ = http_get_json(path, retries=1)
        except IMFError as exc:
            last_error = str(exc)
            continue
        countries = parse_country_codelist(payload) if payload else {}
        if len(countries) >= 50:
            return countries
    raise IMFError(last_error)


def get_countries() -> tuple[dict[str, str], bool]:
    """Return ({code: name}, is_live). Falls back to a built-in list if the IMF codelist is unavailable."""
    shared = _shared()
    if time.monotonic() >= shared.codelist_retry_after:
        try:
            return fetch_country_codelist(), True
        except IMFError:
            shared.codelist_retry_after = time.monotonic() + 300  # do not hammer a failing endpoint
    return dict(FALLBACK_COUNTRIES), False


# --------------------------------------------------------------------------- #
# Calculations
# --------------------------------------------------------------------------- #

SERIES_LABELS = {
    "cpi1": "CPI, Country 1",
    "cpi2": "CPI, Country 2",
    "fx1": "Exchange rate (per USD), Country 1",
    "fx2": "Exchange rate (per USD), Country 2",
}


def load_pair(iso1: str, iso2: str) -> tuple[dict[str, pd.Series | None], list[dict]]:
    """Fetch the four IMF series needed for a pair. Returns (series by tag, request log).

    A series of ``None`` means "the US dollar numeraire" (exchange rate of 1 by definition).
    """
    plan = [
        ("cpi1", CPI_FLOW, CPI_KEY, iso1),
        ("cpi2", CPI_FLOW, CPI_KEY, iso2),
        ("fx1", FX_FLOW, FX_KEY, iso1),
        ("fx2", FX_FLOW, FX_KEY, iso2),
    ]
    series: dict[str, pd.Series | None] = {}
    log: list[dict] = []
    for tag, flow, key_template, iso in plan:
        if flow == FX_FLOW and iso == USD:
            series[tag] = None
            log.append({"Series": SERIES_LABELS[tag], "Code": iso, "Request": "(none: USD is the numeraire, rate = 1)"})
            continue
        key = key_template.format(iso=iso)
        data, url = fetch_series(flow, key)
        series[tag] = data
        log.append({"Series": SERIES_LABELS[tag], "Code": iso, "Request": url})
    return series, log


def build_dataset(
    cpi1: pd.Series, cpi2: pd.Series, fx1: pd.Series | None, fx2: pd.Series | None
) -> pd.DataFrame:
    """Align the monthly inputs and compute S and RER.

    ``fx`` series are local-currency units per USD (``None`` = USD itself, i.e. 1).
    Columns: P1, P2, E1, E2 (inputs), S, valid, RER. A month is *valid* only if S, P1 and P2
    are all available and strictly positive; RER is computed for valid months only.
    """
    present = [s for s in (cpi1, cpi2, fx1, fx2) if s is not None and not s.empty]
    if not present:
        return pd.DataFrame(columns=["P1", "P2", "E1", "E2", "S", "valid", "RER"])
    index = pd.date_range(min(s.index.min() for s in present), max(s.index.max() for s in present), freq="MS")

    def aligned(s: pd.Series | None) -> pd.Series:
        return pd.Series(1.0, index=index) if s is None else s.reindex(index)

    df = pd.DataFrame({"P1": aligned(cpi1), "P2": aligned(cpi2), "E1": aligned(fx1), "E2": aligned(fx2)}, index=index)
    df.index.name = "month"
    df["S"] = (df["E2"] / df["E1"]).where((df["E1"] > 0) & (df["E2"] > 0))  # units of C2 per unit of C1
    df["valid"] = df["S"].notna() & (df["P1"] > 0) & (df["P2"] > 0)
    df["RER"] = (df["S"] * df["P1"] / df["P2"]).where(df["valid"])
    return df


def compute_sample(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, float]:
    """Restrict to [start, end], compute RER* over its valid months and the Real Index."""
    sample = df.loc[start:end].copy()
    rer_star = float(sample.loc[sample["valid"], "RER"].mean()) if sample["valid"].any() else math.nan
    sample["RER_star"] = rer_star
    sample["Real_Index"] = 100.0 * sample["RER"] / rer_star
    return sample, rer_star


EXPORT_COLUMNS = [
    "month", "country1", "country2", "P1_cpi", "P2_cpi", "E1_per_usd", "E2_per_usd",
    "S_nominal", "RER", "RER_star", "Real_Index", "valid_month",
]  # fmt: skip


def export_frame(sample: pd.DataFrame, iso1: str, iso2: str) -> pd.DataFrame:
    """All observations and calculations in the selected sample period (one row per month)."""
    out = sample.rename(
        columns={
            "P1": "P1_cpi", "P2": "P2_cpi", "E1": "E1_per_usd", "E2": "E2_per_usd",
            "S": "S_nominal", "valid": "valid_month",
        }
    ).copy()  # fmt: skip
    out["month"] = sample.index.strftime("%Y-%m")
    out["country1"], out["country2"] = iso1, iso2
    out["valid_month"] = out["valid_month"].astype(int)
    return out[EXPORT_COLUMNS].reset_index(drop=True)


def coverage_table(series: dict[str, pd.Series | None]) -> pd.DataFrame:
    rows = []
    for tag, label in SERIES_LABELS.items():
        s = series[tag]
        if s is None:
            rows.append({"Series": label, "First month": "n/a", "Last month": "n/a", "Observations": "USD = 1"})
        elif s.empty:
            rows.append({"Series": label, "First month": "-", "Last month": "-", "Observations": "0"})
        else:
            rows.append(
                {
                    "Series": label,
                    "First month": s.index.min().strftime("%Y-%m"),
                    "Last month": s.index.max().strftime("%Y-%m"),
                    "Observations": str(int(s.size)),  # text column: the USD row is not numeric
                }
            )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Chart
# --------------------------------------------------------------------------- #


def _short(text: str, limit: int = 24) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_figure(sample: pd.DataFrame, mode: str, name1: str, name2: str) -> go.Figure:
    """Real Index, nominal S, or both (nominal on its own right-hand axis, in actual currency units)."""
    show_real = mode in ("Real", "Both")
    show_nominal = mode in ("Nominal", "Both")
    nominal_title = f"Nominal S ({_short(name2)} per {_short(name1)})"  # full definition is in the caption
    real_title = "Real Index (sample average = 100)"

    fig = go.Figure()
    if show_real:
        fig.add_trace(
            go.Scatter(
                x=sample.index, y=sample["Real_Index"], name="Real Index", mode="lines",
                line=dict(color=REAL_COLOR, width=2), yaxis="y", hovertemplate="%{y:,.2f}",
            )
        )  # fmt: skip
        fig.add_trace(
            go.Scatter(
                x=[sample.index.min(), sample.index.max()], y=[100, 100], name="Sample average (100)",
                mode="lines", line=dict(color=REAL_COLOR, width=1, dash="dot"), opacity=0.6,
                yaxis="y", hoverinfo="skip",
            )
        )  # fmt: skip
    if show_nominal:
        fig.add_trace(
            go.Scatter(
                x=sample.index, y=sample["S"], name="Nominal S", mode="lines",
                line=dict(color=NOMINAL_COLOR, width=2), yaxis="y2" if mode == "Both" else "y",
                hovertemplate="%{y:,.6g}",
            )
        )  # fmt: skip

    if mode == "Real":
        fig.update_yaxes(title=dict(text=real_title))
    elif mode == "Nominal":
        fig.update_yaxes(title=dict(text=nominal_title))
    else:  # Both: separate axes
        fig.update_layout(
            yaxis=dict(
                title=dict(text=real_title, font=dict(color=REAL_COLOR)), tickfont=dict(color=REAL_COLOR)
            ),
            yaxis2=dict(
                title=dict(text=nominal_title, font=dict(color=NOMINAL_COLOR)),
                tickfont=dict(color=NOMINAL_COLOR),
                overlaying="y", side="right", showgrid=False,
            ),
        )  # fmt: skip
    fig.update_layout(
        hovermode="x unified",
        showlegend=True,
        height=520,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig


# --------------------------------------------------------------------------- #
# Streamlit UI
# --------------------------------------------------------------------------- #


def _country_label(code: str, names: dict[str, str]) -> str:
    return f"{names.get(code, code)} ({code})"


def _show_sources(log: list[dict], coverage: pd.DataFrame | None) -> None:
    with st.expander("Data sources, requests and coverage"):
        st.markdown(
            "Source: International Monetary Fund (IMF) SDMX 3.0 API — monthly CPI "
            f"(`IMF.STA/{CPI_FLOW}`) and period-average exchange rates (`IMF.STA/{FX_FLOW}`), from January 1976 where available."
        )
        if coverage is not None:
            st.dataframe(coverage, hide_index=True, width="stretch")
        if log:
            st.dataframe(pd.DataFrame(log), hide_index=True, width="stretch")


def main() -> None:
    st.set_page_config(page_title="Real Exchange Rate Explorer", page_icon="💱", layout="wide")
    st.title("Real Exchange Rate Explorer")
    st.caption(
        "Monthly IMF data  ·  S(t) = units of Country 2 currency per 1 unit of Country 1 currency  ·  "
        "RER(t) = S(t) × P1(t) / P2(t)  ·  Real Index(t) = 100 × RER(t) / RER*"
    )

    with st.sidebar:
        st.header("About")
        st.markdown(
            "**RER\\*** is the average of RER(t) over the valid months of the selected sample, so the "
            "Real Index equals 100 on average. A rising index means Country 1's prices have risen relative "
            "to Country 2's when measured in a common currency (a real appreciation of Country 1's currency)."
        )
        if st.button("Refresh IMF data", help="Clear cached downloads and fetch the latest data from the IMF."):
            st.cache_data.clear()
            st.rerun()

    names, live_list = get_countries()
    codes = sorted(names, key=lambda c: names[c].casefold())
    if not live_list:
        st.info("The IMF country list could not be downloaded, so a built-in list of countries is shown.")

    col1, col2 = st.columns(2)
    iso1 = col1.selectbox(
        "Country 1", codes, index=codes.index(USD) if USD in codes else 0,
        format_func=lambda c: _country_label(c, names), key="country1",
    )  # fmt: skip
    iso2 = col2.selectbox(
        "Country 2", codes, index=codes.index(EURO_AREA) if EURO_AREA in codes else 1,
        format_func=lambda c: _country_label(c, names), key="country2",
    )  # fmt: skip
    if iso1 == iso2:
        st.warning("Please choose two different countries.")
        st.stop()
    name1, name2 = names.get(iso1, iso1), names.get(iso2, iso2)

    # ---- data ------------------------------------------------------------- #
    try:
        with st.spinner("Fetching data from the IMF…"):
            series, log = load_pair(iso1, iso2)
    except IMFError as exc:
        st.error(f"Could not retrieve data from the IMF.\n\n{exc}")
        st.stop()

    coverage = coverage_table(series)
    missing = [
        SERIES_LABELS[tag] + f" — {name1 if tag.endswith('1') else name2} ({iso1 if tag.endswith('1') else iso2})"
        for tag, s in series.items()
        if s is not None and s.empty
    ]
    if missing:
        st.error(
            "The IMF returned no monthly data (from January 1976) for:\n\n"
            + "\n".join(f"- {m}" for m in missing)
            + "\n\nPlease choose a different country or Euro-area combination."
        )
        _show_sources(log, coverage)
        st.stop()

    df = build_dataset(series["cpi1"], series["cpi2"], series["fx1"], series["fx2"])
    valid_months = df.index[df["valid"]]
    if len(valid_months) < 2:
        st.error(
            "Fewer than two months have all of S(t), P1(t) and P2(t) available for this pair "
            "(the series do not overlap enough). See the coverage table below."
        )
        _show_sources(log, coverage)
        st.stop()

    # ---- controls ---------------------------------------------------------- #
    options = pd.date_range(valid_months.min(), valid_months.max(), freq="MS").strftime("%Y-%m").tolist()
    start_label, end_label = st.select_slider(
        "Sample period (start month – end month)",
        options=options,
        value=(options[0], options[-1]),
        key=f"period|{iso1}|{iso2}|{options[0]}|{options[-1]}",
    )

    # ---- calculations (RER* is recomputed whenever the sample changes) ----- #
    start, end = pd.Timestamp(start_label + "-01"), pd.Timestamp(end_label + "-01")
    sample, rer_star = compute_sample(df, start, end)
    n_valid, n_total = int(sample["valid"].sum()), len(sample)

    c_mode, m1, m2 = st.columns([1.4, 1, 1])
    with c_mode:
        mode = st.radio("Chart", ["Real", "Nominal", "Both"], horizontal=True, key="chart_mode")
    if n_valid == 0:
        st.warning("No valid months in the selected sample period. Please widen the period.")
        _show_sources(log, coverage)
        st.stop()
    m1.metric("RER*", f"{rer_star:,.4f}", help="Average of RER(t) over the valid months of the selected sample.")
    m2.metric("Valid months used", f"{n_valid} of {n_total}")

    st.plotly_chart(build_figure(sample, mode, name1, name2), width="stretch", config={"displaylogo": False})
    st.caption(
        f"S(t) = units of {name2} currency per 1 unit of {name1} currency (nominal, not normalized). "
        "Real Index: dotted line = sample average (100)."
    )
    if n_valid < n_total:
        st.caption(
            f"{n_total - n_valid} month(s) in the sample lack data for S, P1 or P2 and are excluded from RER* "
            "and the Real Index (shown as gaps; nothing is interpolated). Nominal S is plotted wherever it is available."
        )

    # ---- download & table --------------------------------------------------- #
    export = export_frame(sample, iso1, iso2)
    st.download_button(
        "Download CSV (selected sample)",
        data=export.to_csv(index=False).encode("utf-8"),
        file_name=f"rer_{iso1}_{iso2}_{start_label}_{end_label}.csv",
        mime="text/csv",
        on_click="ignore",
        icon=":material/download:",
    )
    with st.expander("Show data table"):
        st.dataframe(export, hide_index=True, width="stretch")
    _show_sources(log, coverage)


if __name__ == "__main__":
    main()
