"""
finance.py - the financial math behind the robo-advisor.

Every function here is "pure": numbers in, numbers out, no API calls and no
Streamlit. That keeps the math easy to read, explain, and unit-test.

Conventions used throughout:
  * Returns are MONTHLY simple returns (e.g. 0.01 = +1% in a month).
  * We annualize with 12 periods per year.
  * Weights are fractions that sum to 1 (0.60 = 60%).
"""

import numpy as np
import pandas as pd

PERIODS_PER_YEAR = 12  # monthly data


# ---------------------------------------------------------------------------
# 1. Returns
# ---------------------------------------------------------------------------
def monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple returns from month-end adjusted prices: r_t = P_t / P_(t-1) - 1.

    Adjusted prices already include dividends, so these are total returns.
    The first row has no prior price, so it is dropped.
    """
    return prices.pct_change().dropna(how="all")


def annualized_return(returns: pd.DataFrame | pd.Series) -> pd.Series | float:
    """Arithmetic annualized expected return: mu = 12 * average monthly return."""
    return returns.mean() * PERIODS_PER_YEAR


def annualized_volatility(returns: pd.DataFrame | pd.Series) -> pd.Series | float:
    """Stand-alone annualized volatility: sigma = monthly std * sqrt(12)."""
    return returns.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR)


def annualized_covariance(returns: pd.DataFrame) -> pd.DataFrame:
    """Annualized covariance matrix: Sigma = 12 * (monthly sample covariance).

    The sample covariance divides by (n - 1). Variances (the diagonal) and
    covariances both scale linearly with time, so we multiply by 12.
    """
    return returns.cov(ddof=1) * PERIODS_PER_YEAR


# ---------------------------------------------------------------------------
# 2. Portfolio statistics
# ---------------------------------------------------------------------------
def portfolio_return(weights, mu) -> float:
    """Portfolio expected return: mu_p = w^T mu  (weighted average of returns)."""
    w = np.asarray(weights, dtype=float)
    m = np.asarray(mu, dtype=float)
    _check_same_length(w, m)
    return float(w @ m)


def portfolio_volatility(weights, cov) -> float:
    """Portfolio volatility using the FULL covariance matrix.

        sigma_p = sqrt( w^T  Sigma  w ) = sqrt( sum_i sum_j  w_i * w_j * Sigma_ij )

    The off-diagonal terms (covariances) are what create the diversification
    benefit. This is NOT the weighted average of the individual volatilities,
    which ignores correlation and overstates risk (see naive_weighted_volatility).
    """
    w = np.asarray(weights, dtype=float)
    sigma = np.asarray(cov, dtype=float)
    if sigma.shape != (w.size, w.size):
        raise ValueError(f"Covariance matrix shape {sigma.shape} does not match {w.size} weights.")
    variance = w @ sigma @ w
    # Tiny negative values can appear from floating-point rounding; clip at 0.
    return float(np.sqrt(max(variance, 0.0)))


def naive_weighted_volatility(weights, vols) -> float:
    """Weighted average of stand-alone volatilities: sum_i w_i * sigma_i.

    Shown in the app only for comparison: it is what portfolio risk would be
    if every asset were perfectly correlated (rho = 1).
    """
    w = np.asarray(weights, dtype=float)
    v = np.asarray(vols, dtype=float)
    _check_same_length(w, v)
    return float(w @ v)


def sharpe_ratio(expected_return: float, volatility: float, risk_free: float) -> float:
    """Sharpe ratio = (mu_p - r_f) / sigma_p : excess return per unit of risk.

    Returns NaN if volatility is zero (the ratio is undefined).
    """
    if volatility <= 0:
        return float("nan")
    return (expected_return - risk_free) / volatility


# ---------------------------------------------------------------------------
# 3. Historical backtest
# ---------------------------------------------------------------------------
def growth_of_investment(returns: pd.DataFrame, weights, start_value: float = 10_000.0) -> pd.Series:
    """Value of an investment rebalanced back to `weights` every month.

        portfolio return in month t:  r_p,t = w^T r_t
        wealth:                       W_t   = W_0 * prod_(s<=t) (1 + r_p,s)

    The returned series starts with W_0 one period before the first return.
    """
    w = np.asarray(weights, dtype=float)
    _check_same_length(w, np.empty(returns.shape[1]))
    port_returns = returns.to_numpy() @ w
    wealth = start_value * np.cumprod(1.0 + port_returns)
    wealth = np.concatenate([[start_value], wealth])
    if isinstance(returns.index, pd.DatetimeIndex) and len(returns.index) > 0:
        first = returns.index[0] - pd.offsets.MonthEnd(1)
        index = returns.index.insert(0, first)
    else:
        index = pd.RangeIndex(len(wealth))
    return pd.Series(wealth, index=index, name="Portfolio value")


def cagr(wealth: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """Compound annual growth rate: (W_end / W_start)^(1 / years) - 1.

    `wealth` has one more point than there are return periods, so
    years = (number of points - 1) / periods_per_year.
    """
    n_periods = len(wealth) - 1
    if n_periods <= 0 or wealth.iloc[0] <= 0:
        return float("nan")
    years = n_periods / periods_per_year
    return float((wealth.iloc[-1] / wealth.iloc[0]) ** (1.0 / years) - 1.0)


def max_drawdown(wealth: pd.Series) -> float:
    """Largest peak-to-trough decline: min_t ( W_t / max_(s<=t) W_s - 1 ).

    Returned as a negative fraction, e.g. -0.25 means a 25% fall from a peak.
    """
    running_peak = wealth.cummax()
    drawdowns = wealth / running_peak - 1.0
    return float(drawdowns.min())


# ---------------------------------------------------------------------------
# 4. Monte Carlo projection
# ---------------------------------------------------------------------------
def monte_carlo_paths(
    annual_return: float,
    annual_volatility: float,
    years: int,
    start_value: float = 10_000.0,
    monthly_contribution: float = 0.0,
    n_paths: int = 5_000,
    seed: int | None = 42,
) -> np.ndarray:
    """Simulate future portfolio values month by month.

    Each month's portfolio return is drawn from a normal distribution with
        mean = annual_return / 12     and     std = annual_volatility / sqrt(12)
    (the monthly equivalents of the annual mu and sigma). The contribution is
    added at the end of each month. A fixed seed makes results reproducible.

    Returns an array of shape (n_paths, years * 12 + 1); column 0 is today.
    """
    if years <= 0 or n_paths <= 0:
        raise ValueError("years and n_paths must be positive.")
    n_months = int(years * PERIODS_PER_YEAR)
    rng = np.random.default_rng(seed)
    monthly_mean = annual_return / PERIODS_PER_YEAR
    monthly_std = annual_volatility / np.sqrt(PERIODS_PER_YEAR)
    shocks = rng.normal(monthly_mean, monthly_std, size=(n_paths, n_months))

    values = np.empty((n_paths, n_months + 1))
    values[:, 0] = start_value
    for t in range(n_months):
        values[:, t + 1] = values[:, t] * (1.0 + shocks[:, t]) + monthly_contribution
    # A portfolio cannot go below zero.
    return np.maximum(values, 0.0)


def percentile_bands(paths: np.ndarray, percentiles=(10, 50, 90)) -> pd.DataFrame:
    """Percentile of simulated value at each month (columns = percentiles).

    p10 = a bad outcome (only 10% of paths end lower), p50 = the median,
    p90 = a good outcome (only 10% of paths end higher).
    """
    bands = np.percentile(paths, percentiles, axis=0).T
    return pd.DataFrame(bands, columns=[f"p{p}" for p in percentiles])


def expected_geometric_return(annual_return: float, annual_volatility: float) -> float:
    """Growth rate of the MEDIAN outcome: exp(mu - sigma^2 / 2) - 1.

    Compounding volatile returns grows money more slowly than the arithmetic
    average suggests ("volatility drag" of about sigma^2 / 2 per year). Half of
    the simulated paths end above (1 + g)^years and half below, so this is the
    rate the Monte Carlo median should grow at.
    """
    return float(np.exp(annual_return - annual_volatility**2 / 2) - 1)


def forward_expected_returns(mu: pd.Series, cash_ticker: str, cash_rate: float) -> pd.Series:
    """Expected returns for the projection: historical mu, except cash.

    Today's T-bill rate is a better forecast of next year's cash return than
    the 10-year historical average, so the cash ETF uses `cash_rate` instead.
    """
    forward = mu.copy()
    if cash_ticker in forward.index:
        forward[cash_ticker] = cash_rate
    return forward


# ---------------------------------------------------------------------------
# 5. Putting it together
# ---------------------------------------------------------------------------
def lookback_window(returns: pd.DataFrame, years: int | None) -> pd.DataFrame:
    """Keep only months where every ETF has data, then the most recent `years`.

    years=None means "all common history".
    """
    common = returns.dropna(how="any")
    if years is None:
        return common
    return common.iloc[-int(years * PERIODS_PER_YEAR):]


def portfolio_summary(returns: pd.DataFrame, weights, risk_free: float, start_value: float = 10_000.0) -> dict:
    """All headline statistics for one set of weights over one return window.

    risk_free is an annual decimal (0.02 = 2%). Returns a dict so the app and
    tests can read each number by name.
    """
    mu = annualized_return(returns)
    vols = annualized_volatility(returns)
    cov = annualized_covariance(returns)
    exp_ret = portfolio_return(weights, mu)
    vol = portfolio_volatility(weights, cov)
    wealth = growth_of_investment(returns, weights, start_value)
    return {
        "expected_return": exp_ret,
        "volatility": vol,
        "naive_volatility": naive_weighted_volatility(weights, vols),
        "sharpe": sharpe_ratio(exp_ret, vol, risk_free),
        "cagr": cagr(wealth),
        "max_drawdown": max_drawdown(wealth),
        "wealth": wealth,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _check_same_length(a: np.ndarray, b: np.ndarray) -> None:
    if a.size != b.size:
        raise ValueError(f"Length mismatch: {a.size} weights vs {b.size} assets.")
