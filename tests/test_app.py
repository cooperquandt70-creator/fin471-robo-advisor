"""Smoke tests that run the real Streamlit script headlessly (streamlit.testing.AppTest)."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import data

APP = str(Path(__file__).resolve().parent.parent / "app.py")


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
