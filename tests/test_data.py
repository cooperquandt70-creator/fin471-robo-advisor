"""Offline tests for data.py: the fallback chain and error handling (no network needed)."""

import pandas as pd
import pytest
import requests

import data

TICKERS = ["VTI", "BND"]
SECRET = "super_secret_key_123"


def _prices():
    idx = pd.date_range("2020-01-31", periods=3, freq="ME")
    return pd.DataFrame({"VTI": [100.0, 101.0, 102.0], "BND": [50.0, 50.5, 51.0]}, index=idx)


def _fail(*args, **kwargs):
    raise data.ApiError("simulated outage")


@pytest.fixture
def isolated_files(tmp_path, monkeypatch):
    """Point cache and snapshot paths at a temp folder so tests never touch real files."""
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(data, "CACHE_PRICES", tmp_path / "cache" / "prices.csv")
    monkeypatch.setattr(data, "SNAPSHOT_PRICES", tmp_path / "snapshot.csv")
    return tmp_path


# --- Fallback chain --------------------------------------------------------
def test_uses_yfinance_when_available(isolated_files, monkeypatch):
    monkeypatch.setattr(data, "fetch_prices_yfinance", lambda t: _prices())
    result = data.get_prices(TICKERS)
    assert result.source == "live"
    assert data.CACHE_PRICES.exists()  # a "last good" copy is saved


def test_falls_back_to_tiingo(isolated_files, monkeypatch):
    monkeypatch.setattr(data, "fetch_prices_yfinance", _fail)
    monkeypatch.setattr(data, "fetch_prices_tiingo", lambda t, k: _prices())
    assert data.get_prices(TICKERS).source == "tiingo"


def test_falls_back_to_cache_then_snapshot(isolated_files, monkeypatch):
    monkeypatch.setattr(data, "fetch_prices_yfinance", _fail)
    monkeypatch.setattr(data, "fetch_prices_tiingo", _fail)

    # No cache yet -> bundled snapshot
    with open(data.SNAPSHOT_PRICES, "w") as f:
        f.write("# EDUCATIONAL SAMPLE\n")
        _prices().to_csv(f)
    result = data.get_prices(TICKERS)
    assert result.source == "snapshot"
    assert "educational sample" in result.message
    assert "simulated outage" in result.message  # user sees why

    # With a cache -> cache wins over snapshot
    data.CACHE_DIR.mkdir()
    _prices().to_csv(data.CACHE_PRICES)
    assert data.get_prices(TICKERS).source == "cache"


def test_everything_down_returns_error_instead_of_raising(isolated_files, monkeypatch):
    monkeypatch.setattr(data, "fetch_prices_yfinance", _fail)
    monkeypatch.setattr(data, "fetch_prices_tiingo", _fail)
    result = data.get_prices(TICKERS)
    assert result.source == "error" and result.data is None


def test_missing_ticker_fails_the_source():
    with pytest.raises(data.ApiError, match="BND"):
        data._validate_prices(_prices()[["VTI"]], TICKERS, "Test")


# --- HTTP error mapping ----------------------------------------------------
class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.mark.parametrize(
    "status, expected",
    [(401, "API key is invalid"), (403, "premium-only"), (429, "rate limit"), (500, "HTTP 500")],
)
def test_http_errors_become_friendly_messages(monkeypatch, status, expected):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(status))
    with pytest.raises(data.ApiError, match=expected) as exc:
        data._get_json("https://example.com", "Finnhub", params={"token": SECRET})
    assert SECRET not in str(exc.value)


@pytest.mark.parametrize("error", [requests.Timeout, requests.ConnectionError])
def test_network_errors_never_leak_the_key(monkeypatch, error):
    def boom(*args, **kwargs):
        raise error(f"failed for https://api.example.com/?api_key={SECRET}")

    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(data.ApiError) as exc:
        data._get_json("https://api.example.com", "FRED", params={"api_key": SECRET})
    assert SECRET not in str(exc.value)


def test_invalid_json(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200, payload=None))
    with pytest.raises(data.ApiError, match="not valid JSON"):
        data._get_json("https://example.com", "Tiingo")


# --- Missing keys ----------------------------------------------------------
def test_missing_finnhub_key_gives_message(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    result = data.get_quotes(TICKERS)
    assert result.source == "error" and "FINNHUB_API_KEY" in result.message


def test_missing_fred_key_raises_api_error():
    with pytest.raises(data.ApiError, match="FRED_API_KEY"):
        data.fetch_dtb3(None)


def test_zero_quote_counts_as_unavailable(monkeypatch):
    monkeypatch.setattr(data, "_get_json", lambda *a, **k: {"c": 0, "d": None})
    with pytest.raises(data.ApiError, match="no quote"):
        data.fetch_quote("XYZ", "key")


# --- Month-end resampling --------------------------------------------------
def test_month_end_drops_incomplete_current_month():
    today = pd.Timestamp.today().normalize()
    idx = pd.to_datetime([today - pd.offsets.MonthEnd(2), today - pd.offsets.MonthEnd(1), today])
    monthly = data._to_month_end(pd.DataFrame({"VTI": [1.0, 2.0, 3.0]}, index=idx))
    assert len(monthly) == 2
    assert monthly.index[-1] < today
