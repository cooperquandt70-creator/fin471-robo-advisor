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


def money(at, label):
    return int(metric(at, label).strip("$").replace(",", ""))


def pct(at, label):
    return float(metric(at, label).rstrip("%"))


def custom(at, weights_pct):
    """Turn on manual override and load specific weights into the editor."""
    if not at.toggle(key="override").value:
        at.toggle(key="override").set_value(True).run()
    at.session_state["custom_pct"] = weights_pct
    at.session_state["editor_version"] = at.session_state["editor_version"] + 1
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


def test_negative_weight_rejected():
    at = custom(run_app(), {**ALL_VTI, "VTI": 105.0, "BIL": -5.0})
    assert any("Negative weights" in e.value and "BIL = -5.0%" in e.value for e in at.error)
    assert not [m for m in at.metric if m.label == "Volatility (annual)"]  # stats paused
    assert any("paused" in i.value for i in at.info)


def test_weights_not_100_warn_then_normalize():
    at = custom(run_app(), {**ALL_VTI, "VTI": 45.0, "BND": 45.0})  # 90%
    assert any("90.0%, not 100%" in w.value for w in at.warning)
    assert not [m for m in at.metric if m.label == "Volatility (annual)"]  # not silently normalized

    at.button(key="normalize").click().run()
    assert not at.exception
    assert not any("not 100%" in w.value for w in at.warning)
    assert at.session_state["custom_pct"]["VTI"] == pytest.approx(50.0)
    assert pct(at, "Volatility (annual)") > 0


def test_reset_to_recommended():
    at = custom(run_app(), ALL_VTI)
    at.button(key="reset_weights").click().run()
    assert at.session_state["custom_pct"]["VTI"] == pytest.approx(42.0)  # Moderate +10 tilt


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
