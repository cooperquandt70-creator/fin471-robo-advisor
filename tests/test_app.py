"""Smoke tests that run the real Streamlit script headlessly (streamlit.testing.AppTest)."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import data

APP = str(Path(__file__).resolve().parent.parent / "app.py")
# The real functions, saved before the fixture swaps them out (some tests need them back).
REAL = {name: getattr(data, name) for name in ("fetch_prices_yfinance", "fetch_prices_tiingo", "fetch_dtb3")}


def _offline(*args, **kwargs):
    raise data.ApiError("offline for tests")


@pytest.fixture(autouse=True)
def offline_data(monkeypatch, tmp_path):
    """No network in tests: live sources fail, so the app falls back to the bundled sample."""
    monkeypatch.setattr(data, "fetch_prices_yfinance", _offline)
    monkeypatch.setattr(data, "fetch_prices_tiingo", _offline)
    monkeypatch.setattr(data, "fetch_dtb3", _offline)
    monkeypatch.setattr(data, "CACHE_PRICES", tmp_path / "prices.csv")  # ignore any local cache
    monkeypatch.setattr(data, "CACHE_DTB3", tmp_path / "dtb3.csv")
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def run_app(age=None, horizon=None):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    if age is not None:
        at.number_input(key="age").set_value(age).run()
    if horizon is not None:
        at.slider(key="horizon").set_value(horizon).run()
    assert not at.exception, at.exception
    return at


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def test_app_runs_without_errors_and_shows_disclaimer():
    at = run_app()
    assert not at.exception
    assert any("not investment advice" in i.value for i in at.info)


def test_age_change_resets_horizon_and_changes_recommendation():
    young = run_app(age=25)
    assert young.slider(key="horizon").value == 40
    assert metric(young, "Your profile") == "Moderate"
    assert metric(young, "Growth / defensive") == "70% / 30%"

    older = run_app(age=60)
    assert older.slider(key="horizon").value == 5
    assert metric(older, "Your profile") == "Conservative"
    assert metric(older, "Growth / defensive") == "25% / 75%"


@pytest.mark.parametrize("age", [64, 65, 66, 80])
def test_ages_at_or_past_65_never_give_zero_horizon(age):
    at = run_app(age=age)  # run_app asserts no exception
    assert at.slider(key="horizon").value == 1
    assert metric(at, "Your profile") == "Conservative"
    assert not at.error


def test_horizon_label_and_limitations_note():
    at = run_app()
    assert at.slider(key="horizon").label == "Years until you start withdrawing money"
    assert any("retirement spending" in m.value for m in at.markdown)


def test_statistics_shown_from_snapshot_with_clear_source_badge():
    at = run_app()
    for label in ("Expected return (annual)", "Volatility (annual)", "Sharpe ratio", "Max drawdown"):
        assert metric(at, label) not in ("", "nan%", "nan")
    assert any("educational sample" in w.value for w in at.sidebar.warning)
    assert any("120 monthly total returns" in c.value for c in at.caption)  # 10-year default


def test_lookback_selector_changes_window():
    at = run_app()
    at.selectbox(key="lookback").set_value("5 years").run()
    assert not at.exception
    assert any("60 monthly total returns" in c.value for c in at.caption)


def test_aggressive_has_higher_volatility_than_conservative():
    def vol(age):
        return float(metric(run_app(age=age), "Volatility (annual)").rstrip("%"))
    assert vol(25) > vol(70)


def test_monte_carlo_bands_and_starting_amount():
    at = run_app()
    low = int(metric(at, "Median").strip("$").replace(",", ""))
    p10 = int(next(m.value for m in at.metric if m.label.startswith("Bad case")).strip("$").replace(",", ""))
    p90 = int(metric(at, "Good case (90th pct.)").strip("$").replace(",", ""))
    assert p10 < low < p90

    at.number_input(key="start_amount").set_value(20_000).run()
    assert not at.exception
    doubled = int(metric(at, "Median").strip("$").replace(",", ""))
    # Same seed, no contributions: doubling the start doubles every path.
    assert doubled == pytest.approx(2 * low, abs=2)
    assert any("nominal" in m.value for m in at.markdown)  # Limitations note


def test_monte_carlo_uses_horizon_and_cash_at_current_rate():
    at = run_app(age=60)  # horizon 5 years
    assert any("5-year horizon" in s.value for s in at.subheader)
    assert any("today's T-bill rate" in c.value for c in at.caption)


def test_four_charts_rendered():
    at = run_app()
    charts = at.get("plotly_chart")
    assert len(charts) == 4  # donut, backtest, Monte Carlo, risk/return


def money(at, label):
    """Parse '$12,345', '$12.3M' or '$1.23B' back into dollars."""
    text = metric(at, label).strip("$").replace(",", "")
    scale = {"M": 1e6, "B": 1e9}.get(text[-1], 1)
    return float(text.rstrip("MB")) * scale


def pct(at, label):
    return float(metric(at, label).rstrip("%"))


def custom(at, weights_pct):
    """Turn on manual override and type specific weights into the per-ETF number inputs."""
    if not at.toggle(key="override").value:
        at.toggle(key="override").set_value(True).run()
    for t, v in weights_pct.items():
        at.number_input(key=f"w_{t}").set_value(float(v))
    at.run()
    assert not at.exception, at.exception
    return at


ALL_VTI = {"VTI": 100.0, "VXUS": 0.0, "VNQ": 0.0, "BND": 0.0, "BNDX": 0.0, "TIP": 0.0, "BIL": 0.0}


def test_override_on_starts_from_recommendation_and_is_labelled_custom():
    at = run_app()
    before = metric(at, "Volatility (annual)")
    at.toggle(key="override").set_value(True).run()
    assert not at.exception
    assert any("Custom portfolio" in c.value for c in at.caption)
    assert any("Custom portfolio" in s.value for s in at.subheader)  # "Expected return and risk: Custom portfolio"
    assert not any("Moderate portfolio" in s.value for s in at.subheader)
    assert metric(at, "Volatility (annual)") == before  # same weights, same stats
    assert metric(at, "Your profile") == "Moderate"  # questionnaire result kept


def test_custom_weights_change_statistics():
    at = run_app()
    rec_vol = pct(at, "Volatility (annual)")
    custom(at, ALL_VTI)
    assert pct(at, "Volatility (annual)") > rec_vol  # 100% stocks is riskier than 70/30


def test_weight_inputs_cannot_go_negative():
    # Each input has min 0, so negatives can't even be entered (check_custom_weights also rejects
    # them; see test_profiles.py). Seven inputs, two columns, step 1.
    at = run_app()
    at.toggle(key="override").set_value(True).run()
    inputs = [at.number_input(key=f"w_{t}") for t in ("VTI", "VXUS", "VNQ", "BND", "BNDX", "TIP", "BIL")]
    assert all(i.min == 0 and i.max == 100 and i.step == 1 for i in inputs)
    assert sum(i.value for i in inputs) == pytest.approx(100.0)  # starts from the recommendation


def test_weights_not_100_warn_then_normalize():
    at = custom(run_app(), {**ALL_VTI, "VTI": 45.0, "BND": 45.0})  # 90%
    assert any("90.0%, not 100%" in w.value for w in at.warning)
    assert not [m for m in at.metric if m.label == "Volatility (annual)"]  # not silently normalized

    at.button(key="normalize").click().run()
    assert not at.exception
    assert not any("not 100%" in w.value for w in at.warning)
    assert at.number_input(key="w_VTI").value == pytest.approx(50.0)
    assert pct(at, "Volatility (annual)") > 0


def test_reset_to_recommended():
    at = custom(run_app(), ALL_VTI)
    at.button(key="reset_weights").click().run()
    assert at.number_input(key="w_VTI").value == pytest.approx(42.0)  # Moderate +10 tilt


def test_conservative_adjustment_applies_to_forward_numbers_only():
    at = run_app()
    hist = {k: metric(at, k) for k in ("Expected return (annual)", "Sharpe ratio", "Backtest CAGR",
                                        "$10,000 became", "Max drawdown", "Volatility (annual)", "Median")}
    at.radio(key="return_assumption").set_value("Conservative adjustment").run()
    assert not at.exception
    adj = {k: metric(at, k) for k in hist}

    # Moderate +10 tilt = 70% equity, 27% bonds, 3% cash -> -(0.70*2.0 + 0.27*0.5) = -1.535 points
    drop = float(hist["Expected return (annual)"].rstrip("%")) - float(adj["Expected return (annual)"].rstrip("%"))
    assert drop == pytest.approx(1.535, abs=0.1)  # displayed values are rounded to 0.1%
    assert any("-1.53 pts" in m.delta or "-1.54 pts" in m.delta for m in at.metric if m.delta)
    assert float(adj["Sharpe ratio"]) < float(hist["Sharpe ratio"])
    assert money(at, "Median") < int(hist["Median"].strip("$").replace(",", ""))
    for unchanged in ("Backtest CAGR", "$10,000 became", "Max drawdown", "Volatility (annual)"):
        assert adj[unchanged] == hist[unchanged]
    assert any("-2.0 points" in i.value and "-0.5 points" in i.value for i in at.info)


def test_methodology_mentions_adjustment():
    at = run_app()
    assert any("Conservative adjustment" in m.value and "not** to the historical" in m.value for m in at.markdown)


def test_all_price_sources_down_shows_error_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "SNAPSHOT_PRICES", tmp_path / "missing.csv")
    monkeypatch.setattr(data, "SNAPSHOT_DTB3", tmp_path / "missing_dtb3.csv")
    at = run_app()  # asserts no exception
    assert any("Historical prices are unavailable" in e.value for e in at.error)
    assert metric(at, "Your profile")  # questionnaire results still shown
    assert any("No price data available" in e.value for e in at.sidebar.error)


def test_risk_free_down_asks_for_manual_rate(monkeypatch, tmp_path):
    monkeypatch.setattr(data, "SNAPSHOT_DTB3", tmp_path / "missing_dtb3.csv")
    at = run_app()
    assert any("No risk-free rate data" in e.value for e in at.sidebar.error)
    assert at.number_input(key="rf_manual").value == 4.0
    assert metric(at, "Sharpe ratio") != "nan"
    assert any("(4.00%)" in c.value for c in at.caption)


def test_short_horizon_cap_is_explained():
    at = run_app(horizon=2)
    for q in ("drop_reaction", "goal", "experience", "stability", "tradeoff"):
        at.radio(key=f"q_{q}").set_value(4)
    at.run()
    assert not at.exception
    assert metric(at, "Your profile") == "Conservative"
    assert any("under 3 years" in m.value for m in at.markdown)


# ===========================================================================
# Milestone 8: robustness pass (each test = one row of the README "Testing" table)
# ===========================================================================
import json  # noqa: E402

import requests  # noqa: E402
import yfinance  # noqa: E402
from yfinance.exceptions import YFRateLimitError  # noqa: E402

ALL_ZERO = {t: 0.0 for t in ALL_VTI}


def chart_layout(at, index):
    """Plotly layout dict of the index-th chart on the page."""
    return json.loads(at.get("plotly_chart")[index].proto.spec)["layout"]


def sidebar_text(at):
    return " ".join(e.value for e in [*at.sidebar.success, *at.sidebar.warning, *at.sidebar.error])


# Case 1 - 100% BIL: near-zero volatility must not produce a huge Sharpe
def test_all_cash_sharpe_is_na_with_reason():
    at = custom(run_app(), {**ALL_ZERO, "BIL": 100.0})
    assert metric(at, "Sharpe ratio") == "n/a"
    assert pct(at, "Volatility (annual)") < 1.0
    assert any("Sharpe ratio n/a" in c.value and "below 1%" in c.value for c in at.caption)
    assert money(at, "Median") > 0  # Monte Carlo still runs


# Case 2a - 100% in a single ETF
@pytest.mark.parametrize("ticker", ["VTI", "VNQ", "BND"])
def test_single_etf_portfolio(ticker):
    at = custom(run_app(), {**ALL_ZERO, ticker: 100.0})
    assert metric(at, "Sharpe ratio") != "n/a"
    assert any("Diversification:** none here" in m.value for m in at.markdown)
    assert len(at.get("plotly_chart")) == 4


# Case 2b - all weights 0
def test_all_zero_weights_rejected():
    at = custom(run_app(), ALL_ZERO)
    assert any("All weights are zero" in e.value for e in at.error)
    assert not [m for m in at.metric if m.label == "Volatility (annual)"]
    assert not any(b.key == "normalize" for b in at.button)  # nothing to normalize
    assert any("paused" in i.value for i in at.info)


# Case 3 - 1-year horizon in the Monte Carlo
def test_one_year_horizon_monte_carlo():
    at = run_app(horizon=1)
    assert any("1-year horizon" in s.value for s in at.subheader)
    assert any(m.label == "Bad case (10th pct.) in 1 yr" for m in at.metric)
    p10 = money(at, "Bad case (10th pct.) in 1 yr")
    assert 0 < p10 < money(at, "Median") < money(at, "Good case (90th pct.)")
    assert chart_layout(at, 2)["xaxis"]["title"]["text"] == "Years from today"


# Case 4a - no .env file (no keys at all)
def test_no_env_file(monkeypatch):
    for key in ("FINNHUB_API_KEY", "FRED_API_KEY", "TIINGO_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(data, "fetch_prices_tiingo", REAL["fetch_prices_tiingo"])
    monkeypatch.setattr(data, "fetch_dtb3", REAL["fetch_dtb3"])
    at = run_app()
    text = sidebar_text(at)
    assert "No TIINGO_API_KEY" in text and "No FRED_API_KEY" in text
    assert metric(at, "Sharpe ratio") != "n/a"  # still works from the bundled sample


class _BadKeyResponse:
    def __init__(self, url):
        self.status_code = 400 if "stlouisfed" in url else 401
        self.ok = False

    def json(self):
        return {}


# Case 4b - bad keys
def test_bad_keys(monkeypatch):
    for key in ("FINNHUB_API_KEY", "FRED_API_KEY", "TIINGO_API_KEY"):
        monkeypatch.setenv(key, "invalid_key_0000")
    monkeypatch.setattr(data, "fetch_prices_tiingo", REAL["fetch_prices_tiingo"])
    monkeypatch.setattr(data, "fetch_dtb3", REAL["fetch_dtb3"])
    monkeypatch.setattr(requests, "get", lambda url, **kw: _BadKeyResponse(url))
    at = run_app()
    text = sidebar_text(at)
    assert "Tiingo rejected the request (HTTP 401)" in text
    assert "FRED rejected the request (HTTP 400)" in text
    assert "invalid_key_0000" not in text  # keys never shown
    assert len(at.get("plotly_chart")) == 4


# Case 4c - no network at all
def test_no_network(monkeypatch):
    def no_network(*args, **kwargs):
        raise requests.ConnectionError("network unreachable")

    def yahoo_down(*args, **kwargs):
        raise OSError("network unreachable")

    monkeypatch.setenv("TIINGO_API_KEY", "some_key")
    monkeypatch.setenv("FRED_API_KEY", "some_key")
    for name in REAL:
        monkeypatch.setattr(data, name, REAL[name])
    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(yfinance, "download", yahoo_down)
    at = run_app()
    text = sidebar_text(at)
    assert "Could not connect to Tiingo" in text and "Could not connect to FRED" in text
    assert "educational sample" in text
    assert len(at.get("plotly_chart")) == 4


# Case 4d - yfinance rate-limited: Tiingo takes over (or the sample if Tiingo is unavailable too)
def test_yfinance_rate_limited_falls_back_to_tiingo(monkeypatch):
    monkeypatch.setattr(data, "fetch_prices_yfinance", REAL["fetch_prices_yfinance"])
    monkeypatch.setattr(yfinance, "download", lambda *a, **k: (_ for _ in ()).throw(YFRateLimitError()))
    monkeypatch.setattr(data, "fetch_prices_tiingo", lambda t, k: data.load_snapshot_prices(t))
    at = run_app()
    assert any("Live prices from Tiingo" in s.value and "rate limit" in s.value for s in at.sidebar.success)


def test_yfinance_rate_limited_and_no_tiingo_uses_sample(monkeypatch):
    monkeypatch.setattr(data, "fetch_prices_yfinance", REAL["fetch_prices_yfinance"])
    monkeypatch.setattr(yfinance, "download", lambda *a, **k: (_ for _ in ()).throw(YFRateLimitError()))
    at = run_app()
    assert any("educational sample" in w.value and "rate limit" in w.value for w in at.sidebar.warning)
    assert len(at.get("plotly_chart")) == 4


# Case 5 - $0 monthly contribution and a $10,000,000 starting amount: readable axes
def test_large_starting_amount_axis_in_millions():
    at = run_app()
    at.number_input(key="contribution").set_value(0).run()
    at.number_input(key="start_amount").set_value(10_000_000).run()
    assert not at.exception
    layout = chart_layout(at, 2)
    assert "millions" in layout["yaxis"]["title"]["text"]
    assert layout["yaxis"]["ticksuffix"] == "M"
    assert money(at, "Median") > 10_000_000
    # Compact "$208.1M" instead of "$208,092,513", which got cut off to "$208,092..." in narrow columns
    assert all(metric(at, k).endswith("M") for k in ("Median", "Good case (90th pct.)"))


def test_default_amount_axis_in_dollars():
    layout = chart_layout(run_app(), 2)
    assert layout["yaxis"]["title"]["text"] == "Portfolio value ($, nominal)"
    assert layout["yaxis"].get("ticksuffix", "") == ""
