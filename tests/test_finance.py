"""Unit tests for finance.py using small, hand-checkable numbers."""

import math

import numpy as np
import pandas as pd
import pytest

import finance as fin


# --- Portfolio volatility (the key covariance-matrix test) -----------------
def test_portfolio_volatility_two_assets_uncorrelated():
    # Asset A: 20% vol, Asset B: 10% vol, correlation 0, weights 50/50.
    # Sigma = [[0.20^2, 0], [0, 0.10^2]] = [[0.04, 0], [0, 0.01]]
    # sigma_p = sqrt(0.5^2 * 0.04 + 0.5^2 * 0.01) = sqrt(0.0125) = 0.1118
    cov = np.array([[0.04, 0.0], [0.0, 0.01]])
    w = [0.5, 0.5]
    vol = fin.portfolio_volatility(w, cov)

    assert vol == pytest.approx(0.1118, abs=1e-4)
    # The naive weighted average of vols would be 0.5*0.20 + 0.5*0.10 = 0.15.
    naive = fin.naive_weighted_volatility(w, [0.20, 0.10])
    assert naive == pytest.approx(0.15)
    assert vol != pytest.approx(0.15, abs=1e-3)


def test_portfolio_volatility_two_assets_correlated():
    # Same assets with rho = 0.5: cov_AB = 0.5 * 0.20 * 0.10 = 0.01
    # sigma_p^2 = 0.25*0.04 + 0.25*0.01 + 2*0.25*0.01 = 0.0175 -> 0.13229
    cov = np.array([[0.04, 0.01], [0.01, 0.01]])
    assert fin.portfolio_volatility([0.5, 0.5], cov) == pytest.approx(math.sqrt(0.0175))


def test_portfolio_volatility_perfect_correlation_equals_weighted_average():
    # With rho = 1 there is no diversification benefit: sigma_p = 0.15.
    cov = np.array([[0.04, 0.02], [0.02, 0.01]])
    assert fin.portfolio_volatility([0.5, 0.5], cov) == pytest.approx(0.15)


def test_portfolio_volatility_shape_mismatch_raises():
    with pytest.raises(ValueError):
        fin.portfolio_volatility([0.5, 0.5], np.eye(3))


# --- Returns and annualization ---------------------------------------------
def test_monthly_returns_from_prices():
    prices = pd.DataFrame({"A": [100.0, 110.0, 99.0]})
    r = fin.monthly_returns(prices)["A"].to_list()
    assert r == pytest.approx([0.10, -0.10])


def test_annualized_return_and_covariance():
    # Monthly returns 1% and 3%: mean 2% -> 24% per year.
    # Sample variance = ((-0.01)^2 + 0.01^2) / (2 - 1) = 0.0002 -> x12 = 0.0024
    r = pd.DataFrame({"A": [0.01, 0.03]})
    assert fin.annualized_return(r)["A"] == pytest.approx(0.24)
    assert fin.annualized_covariance(r).loc["A", "A"] == pytest.approx(0.0024)
    assert fin.annualized_volatility(r)["A"] == pytest.approx(math.sqrt(0.0024))


def test_portfolio_return_is_weighted_average():
    assert fin.portfolio_return([0.6, 0.4], [0.10, 0.04]) == pytest.approx(0.076)


# --- Sharpe ----------------------------------------------------------------
def test_sharpe_ratio():
    # (8% - 3%) / 10% = 0.5
    assert fin.sharpe_ratio(0.08, 0.10, 0.03) == pytest.approx(0.5)


def test_sharpe_ratio_zero_volatility_is_nan():
    assert math.isnan(fin.sharpe_ratio(0.05, 0.0, 0.03))


# --- Backtest, CAGR, drawdown ----------------------------------------------
def test_growth_of_investment_single_asset():
    # $10,000 * 1.10 * 0.90 = $9,900
    r = pd.DataFrame({"A": [0.10, -0.10]})
    wealth = fin.growth_of_investment(r, [1.0])
    assert wealth.to_list() == pytest.approx([10_000, 11_000, 9_900])


def test_growth_of_investment_rebalanced_two_assets():
    # 50/50, A gains 10%, B flat: portfolio +5% -> $10,500
    r = pd.DataFrame({"A": [0.10], "B": [0.0]})
    assert fin.growth_of_investment(r, [0.5, 0.5]).iloc[-1] == pytest.approx(10_500)


def test_cagr():
    # 100 -> 121 over 24 months (2 years): sqrt(1.21) - 1 = 10%
    wealth = pd.Series([100.0] + [0.0] * 23 + [121.0])
    assert fin.cagr(wealth) == pytest.approx(0.10)


def test_max_drawdown():
    # Path 100 -> 120 -> 90 -> 110: worst fall is 120 -> 90 = -25%
    wealth = pd.Series([100.0, 120.0, 90.0, 110.0])
    assert fin.max_drawdown(wealth) == pytest.approx(-0.25)


def test_max_drawdown_never_falls_is_zero():
    assert fin.max_drawdown(pd.Series([100.0, 101.0, 105.0])) == pytest.approx(0.0)


# --- Lookback window and summary --------------------------------------------
def test_lookback_window_drops_incomplete_rows_then_takes_recent_years():
    idx = pd.date_range("2020-01-31", periods=30, freq="ME")
    r = pd.DataFrame({"A": 0.01, "B": 0.0}, index=idx)
    r.iloc[:3, 1] = float("nan")  # B starts late (like BNDX)
    assert len(fin.lookback_window(r, None)) == 27
    assert len(fin.lookback_window(r, 2)) == 24
    assert fin.lookback_window(r, 2).index[-1] == idx[-1]


def test_portfolio_summary_hand_checked():
    # A alternates +2%/0% (mean 1%/month), B is always 0.5%. 50/50.
    r = pd.DataFrame({"A": [0.02, 0.0, 0.02, 0.0], "B": [0.005] * 4})
    s = fin.portfolio_summary(r, [0.5, 0.5], risk_free=0.03)
    assert s["expected_return"] == pytest.approx(0.5 * 0.12 + 0.5 * 0.06)  # 9%
    # B has zero variance, so sigma_p = 0.5 * sigma_A
    sigma_a = fin.annualized_volatility(r["A"])
    assert s["volatility"] == pytest.approx(0.5 * sigma_a)
    assert s["sharpe"] == pytest.approx((0.09 - 0.03) / (0.5 * sigma_a))
    assert s["max_drawdown"] == pytest.approx(0.0)  # never falls
    assert s["wealth"].iloc[-1] == pytest.approx(10_000 * 1.0125**2 * 1.0025**2)


def test_adjust_expected_returns():
    mu = pd.Series({"EQ": 0.10, "BD": 0.04, "CASH": 0.03})
    adj = fin.adjust_expected_returns(mu, {"EQ": -0.02, "BD": -0.005})
    assert adj.to_dict() == pytest.approx({"EQ": 0.08, "BD": 0.035, "CASH": 0.03})
    assert mu["EQ"] == pytest.approx(0.10)  # original unchanged


def test_conservative_adjustment_changes_forward_stats_but_not_backtest():
    # 60% equity / 40% bond. Adjusting equity -2 pts and bonds -0.5 pts should lower the
    # expected return by exactly 0.6*0.02 + 0.4*0.005 = 1.4 points, change Sharpe
    # accordingly, and leave volatility and every backtest number untouched.
    r = pd.DataFrame({"EQ": [0.03, -0.01, 0.02, 0.00], "BD": [0.004, 0.002, 0.003, 0.001]})
    w = [0.6, 0.4]
    hist = fin.portfolio_summary(r, w, risk_free=0.02)
    adjusted_mu = fin.adjust_expected_returns(fin.annualized_return(r), {"EQ": -0.02, "BD": -0.005})
    adj = fin.portfolio_summary(r, w, risk_free=0.02, expected_returns=adjusted_mu)

    assert hist["expected_return"] - adj["expected_return"] == pytest.approx(0.014)
    assert adj["sharpe"] == pytest.approx((adj["expected_return"] - 0.02) / hist["volatility"])
    assert adj["sharpe"] < hist["sharpe"]
    for key in ("volatility", "cagr", "max_drawdown"):
        assert adj[key] == pytest.approx(hist[key])
    assert adj["wealth"].equals(hist["wealth"])


# --- Monte Carlo -----------------------------------------------------------
def test_monte_carlo_zero_volatility_is_deterministic():
    # 12%/yr with no risk = 1% per month: 10,000 * 1.01^12 = 11,268.25
    paths = fin.monte_carlo_paths(0.12, 0.0, years=1, n_paths=10)
    assert paths.shape == (10, 13)
    assert paths[:, -1] == pytest.approx(10_000 * 1.01**12)


def test_monte_carlo_contributions():
    # 0% return, 0 vol, $100/month for 12 months: 10,000 + 1,200
    paths = fin.monte_carlo_paths(0.0, 0.0, years=1, monthly_contribution=100, n_paths=5)
    assert paths[:, -1] == pytest.approx(11_200)


def test_monte_carlo_seed_is_reproducible_and_bands_ordered():
    a = fin.monte_carlo_paths(0.07, 0.15, years=5, n_paths=500, seed=1)
    b = fin.monte_carlo_paths(0.07, 0.15, years=5, n_paths=500, seed=1)
    assert np.array_equal(a, b)
    bands = fin.percentile_bands(a)
    assert list(bands.columns) == ["p10", "p50", "p90"]
    last = bands.iloc[-1]
    assert last["p10"] < last["p50"] < last["p90"]


def test_expected_geometric_return_volatility_drag():
    # mu 8%, sigma 15%: exp(0.08 - 0.01125) - 1 = 7.117%
    assert fin.expected_geometric_return(0.08, 0.15) == pytest.approx(math.exp(0.06875) - 1)
    assert fin.expected_geometric_return(0.08, 0.0) == pytest.approx(math.exp(0.08) - 1)


def test_monte_carlo_median_grows_at_geometric_return():
    # The median path's annual growth should match exp(mu - sigma^2/2) - 1,
    # i.e. noticeably BELOW the 8% arithmetic expected return.
    mu, sigma, years = 0.08, 0.15, 30
    paths = fin.monte_carlo_paths(mu, sigma, years, start_value=10_000, n_paths=20_000, seed=7)
    median_final = fin.percentile_bands(paths).iloc[-1]["p50"]
    median_cagr = (median_final / 10_000) ** (1 / years) - 1
    assert median_cagr == pytest.approx(fin.expected_geometric_return(mu, sigma), abs=0.002)
    assert median_cagr < mu - 0.005


def test_forward_expected_returns_replaces_only_cash():
    mu = pd.Series({"VTI": 0.12, "BIL": 0.015})
    fwd = fin.forward_expected_returns(mu, "BIL", 0.04)
    assert fwd["BIL"] == pytest.approx(0.04)
    assert fwd["VTI"] == pytest.approx(0.12)
    assert mu["BIL"] == pytest.approx(0.015)  # original not modified


# --- Robustness (M8) ---------------------------------------------------------
def test_sharpe_na_below_minimum_volatility():
    # 100% T-bills: ~0.5% volatility would turn a 0.1% excess return into a misleading ratio
    assert math.isnan(fin.sharpe_ratio(0.025, 0.005, 0.02, min_volatility=fin.MIN_VOLATILITY_FOR_SHARPE))
    assert fin.sharpe_ratio(0.025, 0.05, 0.02, min_volatility=fin.MIN_VOLATILITY_FOR_SHARPE) == pytest.approx(0.1)


def test_portfolio_summary_near_constant_returns_gives_nan_sharpe_not_inf():
    r = pd.DataFrame({"CASH": [0.0020, 0.0021, 0.0020, 0.0019]})
    s = fin.portfolio_summary(r, [1.0], risk_free=0.02)
    assert math.isnan(s["sharpe"])
    assert s["volatility"] < 0.01


def test_monte_carlo_one_year_and_large_start():
    paths = fin.monte_carlo_paths(0.07, 0.15, years=1, start_value=10_000_000, n_paths=1_000)
    assert paths.shape == (1_000, 13)
    bands = fin.percentile_bands(paths).iloc[-1]
    assert bands["p10"] < 10_000_000 * 1.07 < bands["p90"]
