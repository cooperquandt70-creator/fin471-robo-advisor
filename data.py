"""
data.py - every external data call lives here.

Sources (see docs/PLAN.md, Step 0):
  * Prices:  yfinance (no key)  ->  Tiingo (free key)  ->  last good local copy
             ->  bundled educational sample (data/snapshot_prices.csv)
  * Risk-free rate: FRED series DTB3 (3-month T-bill)  ->  local copy  ->  sample
  * Live quotes: Finnhub /quote (free tier)

Every public function returns a DataResult instead of raising, so the app can
always show *something* plus a clear message. Error messages never include API
keys (we write our own messages instead of printing raw exception text, which
can contain the request URL).
"""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
SNAPSHOT_PRICES = ROOT / "data" / "snapshot_prices.csv"
SNAPSHOT_DTB3 = ROOT / "data" / "snapshot_dtb3.csv"
CACHE_DIR = ROOT / "data" / "cache"          # git-ignored "last good" copies
CACHE_PRICES = CACHE_DIR / "prices.csv"
CACHE_DTB3 = CACHE_DIR / "dtb3.csv"

HISTORY_START = "2013-01-01"  # BNDX starts mid-2013; the app slices the lookback
TIMEOUT = 15                  # seconds per HTTP request

FINNHUB_URL = "https://finnhub.io/api/v1"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
TIINGO_URL = "https://api.tiingo.com/tiingo/daily"


@dataclass
class DataResult:
    data: object        # DataFrame / Series / None
    source: str         # "live", "tiingo", "cache", "snapshot" or "error"
    message: str = ""   # human-readable status for the UI


class ApiError(Exception):
    """An API call failed; the message is safe to show to users."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def get_key(name: str) -> str | None:
    """Read an API key from the environment (.env). Empty values count as missing."""
    value = os.getenv(name, "").strip()
    return value or None


def _get_json(url: str, service: str, params=None, headers=None):
    """GET a URL and return parsed JSON, translating failures into ApiError."""
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    except requests.Timeout:
        raise ApiError(f"{service} did not respond within {TIMEOUT} seconds.") from None
    except requests.RequestException:
        raise ApiError(f"Could not connect to {service} (network down or service unavailable).") from None

    if resp.status_code in (401, 403):
        raise ApiError(f"{service} rejected the request (HTTP {resp.status_code}): "
                       "the API key is invalid or the endpoint is premium-only.")
    if resp.status_code == 429:
        raise ApiError(f"{service} rate limit reached (HTTP 429). Try again in a minute.")
    if resp.status_code == 400 and service == "FRED":
        raise ApiError("FRED rejected the request (HTTP 400): the API key is probably invalid.")
    if not resp.ok:
        raise ApiError(f"{service} returned HTTP {resp.status_code}.")
    try:
        return resp.json()
    except ValueError:
        raise ApiError(f"{service} returned a response that was not valid JSON.") from None


def _to_month_end(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily (or any) prices -> last price of each calendar month, dropping the
    current, still-incomplete month."""
    prices = prices.sort_index()
    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    monthly = prices.resample("ME").last()
    current_month_end = pd.Timestamp(date.today()) + pd.offsets.MonthEnd(0)
    monthly = monthly[monthly.index < current_month_end.normalize()]
    return monthly


def _validate_prices(prices: pd.DataFrame, tickers: list[str], service: str) -> pd.DataFrame:
    """Make sure every ticker came back with real data; otherwise fail the source."""
    if prices is None or prices.empty:
        raise ApiError(f"{service} returned no price data.")
    missing = [t for t in tickers if t not in prices.columns or prices[t].dropna().empty]
    if missing:
        raise ApiError(f"{service} returned no data for: {', '.join(missing)}.")
    return prices[tickers]


def _read_csv_series(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, comment="#", index_col=0, parse_dates=True)


def _save_cache(df: pd.DataFrame | pd.Series, path: Path) -> None:
    """Keep a local 'last good' copy. Failure to write is not fatal."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
def fetch_prices_yfinance(tickers: list[str], start: str = HISTORY_START) -> pd.DataFrame:
    """Month-end dividend-adjusted closes from Yahoo Finance via yfinance (no key)."""
    import yfinance as yf  # imported here so a yfinance problem can't break app start-up

    try:
        raw = yf.download(tickers, start=start, interval="1d", auto_adjust=True,
                          progress=False, threads=True)
    except Exception:  # yfinance raises many types (rate limit, JSON, network)
        raise ApiError("yfinance (Yahoo Finance) failed or is rate-limited.") from None
    if raw is None or raw.empty or "Close" not in raw.columns.get_level_values(0):
        raise ApiError("yfinance (Yahoo Finance) returned no data (possibly rate-limited).")
    closes = raw["Close"]
    if isinstance(closes, pd.Series):  # single ticker
        closes = closes.to_frame(tickers[0])
    return _validate_prices(_to_month_end(closes), tickers, "yfinance")


def fetch_prices_tiingo(tickers: list[str], api_key: str | None, start: str = HISTORY_START) -> pd.DataFrame:
    """Month-end adjusted closes from Tiingo (free key, ~50 requests/hour)."""
    if not api_key:
        raise ApiError("No TIINGO_API_KEY in .env, so the Tiingo fallback was skipped.")
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}
    series = {}
    for t in tickers:
        rows = _get_json(f"{TIINGO_URL}/{t}/prices", "Tiingo",
                         params={"startDate": start, "resampleFreq": "monthly"}, headers=headers)
        if not isinstance(rows, list) or not rows:
            raise ApiError(f"Tiingo returned no data for {t}.")
        df = pd.DataFrame(rows)
        idx = pd.to_datetime(df["date"]).dt.tz_localize(None)
        series[t] = pd.Series(df["adjClose"].to_numpy(), index=idx)
    return _validate_prices(_to_month_end(pd.DataFrame(series)), tickers, "Tiingo")


def load_snapshot_prices(tickers: list[str]) -> pd.DataFrame:
    """Bundled educational sample (may be stale). Raises ApiError if unusable."""
    if not SNAPSHOT_PRICES.exists():
        raise ApiError("The bundled sample file data/snapshot_prices.csv is missing.")
    return _validate_prices(_read_csv_series(SNAPSHOT_PRICES), tickers, "Snapshot file")


def get_prices(tickers: list[str]) -> DataResult:
    """Try each price source in order and report which one was used."""
    problems = []
    try:
        prices = fetch_prices_yfinance(tickers)
        _save_cache(prices, CACHE_PRICES)
        return DataResult(prices, "live", "Live prices from Yahoo Finance (yfinance).")
    except ApiError as e:
        problems.append(str(e))
    try:
        prices = fetch_prices_tiingo(tickers, get_key("TIINGO_API_KEY"))
        _save_cache(prices, CACHE_PRICES)
        return DataResult(prices, "tiingo", "Live prices from Tiingo (yfinance unavailable).")
    except ApiError as e:
        problems.append(str(e))
    try:
        if CACHE_PRICES.exists():
            prices = _validate_prices(_read_csv_series(CACHE_PRICES), tickers, "Local cache")
            last = prices.index[-1].strftime("%b %Y")
            return DataResult(prices, "cache", f"Using last saved prices (through {last}). " + " ".join(problems))
    except (ApiError, ValueError, OSError) as e:
        problems.append(str(e))
    try:
        prices = load_snapshot_prices(tickers)
        last = prices.index[-1].strftime("%b %Y")
        return DataResult(prices, "snapshot",
                          f"Using the bundled educational sample (through {last}, may be stale). " + " ".join(problems))
    except (ApiError, ValueError, OSError) as e:
        problems.append(str(e))
    return DataResult(None, "error", "No price data available. " + " ".join(problems))


# ---------------------------------------------------------------------------
# Risk-free rate (FRED)
# ---------------------------------------------------------------------------
def fetch_dtb3(api_key: str | None, start: str = HISTORY_START) -> pd.Series:
    """3-month T-bill rate (DTB3, percent per year) from FRED, monthly averages."""
    if not api_key:
        raise ApiError("No FRED_API_KEY in .env.")
    payload = _get_json(FRED_URL, "FRED", params={
        "series_id": "DTB3", "api_key": api_key, "file_type": "json",
        "observation_start": start, "frequency": "m", "aggregation_method": "avg",
    })
    obs = payload.get("observations", []) if isinstance(payload, dict) else []
    df = pd.DataFrame(obs)
    if df.empty:
        raise ApiError("FRED returned no DTB3 observations.")
    values = pd.to_numeric(df["value"], errors="coerce")  # FRED uses "." for missing
    idx = pd.to_datetime(df["date"]) + pd.offsets.MonthEnd(0)
    series = pd.Series(values.to_numpy(), index=idx, name="DTB3").dropna()
    if series.empty:
        raise ApiError("FRED DTB3 data contained no usable values.")
    return series


def get_risk_free() -> DataResult:
    """DTB3 monthly series (percent): FRED -> local copy -> bundled sample."""
    problems = []
    try:
        s = fetch_dtb3(get_key("FRED_API_KEY"))
        _save_cache(s, CACHE_DTB3)
        return DataResult(s, "live", "3-month T-bill rate (DTB3) from FRED.")
    except ApiError as e:
        problems.append(str(e))
    for path, source, label in ((CACHE_DTB3, "cache", "last saved"), (SNAPSHOT_DTB3, "snapshot", "bundled sample")):
        try:
            if path.exists():
                s = _read_csv_series(path).iloc[:, 0].dropna()
                if not s.empty:
                    return DataResult(s, source, f"Using {label} T-bill rates. " + " ".join(problems))
        except (ValueError, OSError, IndexError):
            continue
    return DataResult(None, "error", "No risk-free rate data available. " + " ".join(problems))


# ---------------------------------------------------------------------------
# Live quotes (Finnhub)
# ---------------------------------------------------------------------------
def fetch_quote(symbol: str, api_key: str | None) -> dict:
    """Finnhub /quote: c = current price, d = change, dp = % change, pc = previous close."""
    if not api_key:
        raise ApiError("No FINNHUB_API_KEY in .env.")
    q = _get_json(f"{FINNHUB_URL}/quote", "Finnhub", params={"symbol": symbol},
                  headers={"X-Finnhub-Token": api_key})
    if not isinstance(q, dict) or not q.get("c"):
        raise ApiError(f"Finnhub has no quote for {symbol}.")
    return q


def get_quotes(tickers: list[str]) -> DataResult:
    """Quotes for each ticker; a ticker that fails is shown as unavailable."""
    key = get_key("FINNHUB_API_KEY")
    if not key:
        return DataResult(None, "error", "Live quotes are off: add FINNHUB_API_KEY to .env.")
    rows, failures = [], []
    for t in tickers:
        try:
            q = fetch_quote(t, key)
            rows.append({"Ticker": t, "Price": q["c"], "Change": q.get("d"),
                         "Change %": q.get("dp"), "Prev close": q.get("pc"),
                         "As of": pd.to_datetime(q.get("t"), unit="s", errors="coerce")})
        except ApiError as e:
            failures.append(str(e))
            # Stop early on key/rate-limit problems: every other call would fail too.
            if "rejected" in str(e) or "rate limit" in str(e) or "connect" in str(e):
                break
    if not rows:
        return DataResult(None, "error", "Live quotes unavailable. " + (failures[0] if failures else ""))
    msg = "Live quotes from Finnhub." + (f" Some quotes unavailable: {failures[0]}" if failures else "")
    return DataResult(pd.DataFrame(rows).set_index("Ticker"), "live", msg)


# ---------------------------------------------------------------------------
# Streamlit-cached wrappers (used by app.py to limit API calls)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=24 * 3600, show_spinner="Loading historical prices...")
def cached_prices(tickers: tuple[str, ...]) -> DataResult:
    return get_prices(list(tickers))


@st.cache_data(ttl=24 * 3600, show_spinner="Loading T-bill rates from FRED...")
def cached_risk_free() -> DataResult:
    return get_risk_free()


@st.cache_data(ttl=300, show_spinner="Loading live quotes...")
def cached_quotes(tickers: tuple[str, ...]) -> DataResult:
    return get_quotes(list(tickers))
