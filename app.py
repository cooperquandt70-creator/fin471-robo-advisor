"""
app.py - Streamlit user interface for the FIN471 robo-advisor.

UI only: scoring and allocations come from profiles.py, the math from
finance.py, and all API calls from data.py.

Run with:  streamlit run app.py
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import data
import finance as fin
import profiles as pr

st.set_page_config(page_title="FIN471 Robo-Advisor", page_icon="📊", layout="wide")

# One fixed colour per ETF so every chart matches: blues/purple for growth, greens/grey for defensive.
ETF_COLORS = {
    "VTI": "#1f4e9c", "VXUS": "#4a90d9", "VNQ": "#8e6cc9",
    "BND": "#2e8b57", "BNDX": "#66bb6a", "TIP": "#a5d6a7", "BIL": "#9e9e9e",
}

# Shown in the "Limitations" section (expanded with full content in milestone 9).
LIMITATIONS = [
    "**Horizon is simplified.** The app uses the years until you *start* withdrawing money. In reality, "
    "retirement spending is spread over many years after that date, so the true investment horizon is "
    "longer than this input suggests. That is why the minimum is 1 year rather than 0, even at age 65 or older.",
    "**The 10-year lookback is unusual.** It overweights an unusually strong decade for US stocks and "
    "includes the 2022 bond drawdown. Expected returns are illustrative, not forecasts.",
    "**Projections are in nominal dollars.** Monte Carlo values are not adjusted for inflation: at 2.5% "
    "inflation, $1 thirty years from now buys only about 48 cents of today's goods.",
    "**The Monte Carlo assumes normal, independent monthly returns** with the historical mean and "
    "covariance. Real markets have fatter tails (crashes are more likely than a normal curve predicts), "
    "and future averages may differ from the past decade's.",
]

PROFILE_COLORS = {"Conservative": "#2e8b57", "Moderate": "#e0a030", "Aggressive": "#8e6cc9"}
LOOKBACKS = {"5 years": 5, "10 years": 10, "Max common history": None}
MIN_MONTHS = 24  # fewer monthly returns than this makes the estimates unreliable

DISCLAIMER = (
    "**Educational illustration only - not investment advice.** This tool was built for a "
    "university finance course. It does not know your full financial situation, taxes, or goals, "
    "and past returns do not predict future results. Talk to a licensed professional before investing."
)


# ---------------------------------------------------------------------------
# Sidebar: questionnaire
# ---------------------------------------------------------------------------
def _reset_horizon_to_default():
    """When age changes, move the horizon slider to the default (years until 65)."""
    st.session_state.horizon = pr.default_horizon(st.session_state.age)


def questionnaire() -> tuple[int, dict]:
    st.sidebar.header("1. About you")
    st.sidebar.number_input("Age", min_value=18, max_value=90, value=30, step=1,
                            key="age", on_change=_reset_horizon_to_default)
    if "horizon" not in st.session_state:
        st.session_state.horizon = pr.default_horizon(st.session_state.age)
    horizon = st.sidebar.slider(
        "Years until you start withdrawing money", pr.MIN_HORIZON, pr.MAX_HORIZON, key="horizon",
        help="Defaults to years until age 65 (minimum 1 year, so it is never zero at or past 65). "
             "Adjust it if you plan to start withdrawing earlier or later.",
    )

    st.sidebar.header("2. Risk tolerance")
    answers = {}
    for q in pr.QUESTIONS:
        labels = [label for label, _ in q["options"]]
        choice = st.sidebar.radio(q["text"], range(len(labels)), index=2,
                                  format_func=lambda i, labels=labels: labels[i], key=f"q_{q['key']}")
        answers[q["key"]] = q["options"][choice][1]
    return horizon, answers


def analysis_settings() -> dict:
    st.sidebar.header("3. Analysis settings")
    choice = st.sidebar.selectbox(
        "Historical lookback", list(LOOKBACKS), index=1, key="lookback",
        help="How many years of monthly returns are used to estimate return, volatility and correlation.",
    )
    start = st.sidebar.number_input(
        "Starting amount ($)", min_value=100, max_value=10_000_000, value=10_000, step=1_000, key="start_amount",
        help="Amount invested today in the Monte Carlo projection.",
    )
    contribution = st.sidebar.number_input(
        "Monthly contribution ($)", min_value=0, max_value=100_000, value=0, step=100, key="contribution",
        help="Added at the end of every month in the projection (optional).",
    )
    return {"years": LOOKBACKS[choice], "start": float(start), "contribution": float(contribution)}


def show_source(label: str, result: data.DataResult) -> None:
    """Sidebar badge showing where a dataset came from."""
    text = f"**{label}:** {result.message}"
    if result.source in ("live", "tiingo"):
        st.sidebar.success(text)
    elif result.source in ("cache", "snapshot"):
        st.sidebar.warning(text)
    else:
        st.sidebar.error(text)


def resolve_risk_free(rf_result: data.DataResult, window: pd.DataFrame) -> tuple[float, float]:
    """Return (average rate over the lookback window, latest rate) as annual decimals.

    If FRED and every fallback failed, ask the user for a rate instead of crashing.
    """
    series = rf_result.data
    if series is None or len(series) == 0:
        manual = st.sidebar.number_input("Risk-free rate to use (%)", 0.0, 15.0, 4.0, 0.25, key="rf_manual",
                                         help="FRED data is unavailable, so enter a T-bill rate manually.")
        return manual / 100, manual / 100
    in_window = series.reindex(window.index).dropna()
    average = in_window.mean() if len(in_window) else series.mean()
    return float(average) / 100, float(series.iloc[-1]) / 100


# ---------------------------------------------------------------------------
# Main page sections
# ---------------------------------------------------------------------------
def show_profile(rec: pr.Recommendation) -> None:
    s = rec.score
    growth = pr.growth_share(rec.weights)
    c1, c2, c3 = st.columns(3)
    c1.metric("Your profile", s.profile)
    c2.metric("Risk score", f"{s.total} / 30")
    c3.metric("Growth / defensive", f"{growth:.0%} / {1 - growth:.0%}")

    st.markdown(f"**Why you landed here:** {pr.explain(s)}")
    with st.expander("Score breakdown and scoring rules"):
        breakdown = pd.DataFrame(s.breakdown, columns=["Item", "Points", "Max"])
        st.dataframe(breakdown, hide_index=True, width="stretch")
        st.markdown(
            "- **Horizon points:** under 3 yrs = 0, 3-5 = 2, 6-10 = 5, 11-20 = 8, over 20 = 10\n"
            "- **Each risk question:** 0 (most cautious) to 4 (most risk-tolerant)\n"
            "- **Profile:** 0-12 Conservative, 13-21 Moderate, 22-30 Aggressive\n"
            "- **Safety caps:** horizon under 3 yrs → Conservative; 3-5 yrs → at most Moderate"
        )


def allocation_table(rec: pr.Recommendation) -> pd.DataFrame:
    rows = []
    for t in pr.TICKERS:
        name, asset_class = pr.ETF_INFO[t]
        # Weights first so they stay visible on narrow screens; long fund name last.
        rows.append({
            "Ticker": t, "Your weight": rec.weights[t], "Base weight": rec.base_weights[t],
            "Asset class": asset_class, "Sleeve": "Growth" if t in pr.GROWTH else "Defensive",
            "ETF": name,
        })
    return pd.DataFrame(rows)


def show_allocation(rec: pr.Recommendation) -> None:
    st.subheader("Recommended ETF allocation")
    table = allocation_table(rec)
    tilt = rec.tilt
    direction = "toward growth" if tilt > 0 else "toward defensive assets" if tilt < 0 else "no shift"
    st.caption(
        f"Starting from the {rec.score.profile} base mix, your {rec.score.horizon_years}-year horizon applies a "
        f"**{tilt:+.0%} tilt ({direction})**: (horizon - 10 yrs) x 1 percentage point per year, capped at ±10. "
        "The shift is spread proportionally inside each sleeve, so the mix of US vs international "
        "stocks (and of the bond funds) stays the same."
    )

    left, right = st.columns([3, 2])
    with left:
        shown = table.assign(**{c: table[c] * 100 for c in ("Your weight", "Base weight")})
        st.dataframe(
            shown, hide_index=True, width="stretch",
            column_config={
                "Your weight": st.column_config.NumberColumn(format="%.1f%%"),
                "Base weight": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
    with right:
        chart_data = table[table["Your weight"] > 0.0005]
        fig = px.pie(chart_data, names="Ticker", values="Your weight", hole=0.55,
                     color="Ticker", color_discrete_map=ETF_COLORS,
                     custom_data=["Asset class"])
        # One decimal place, matching the table.
        fig.update_traces(texttemplate="%{label}<br>%{percent:.1%}", sort=False,
                          hovertemplate="%{label}: %{percent:.1%}<br>%{customdata[0]}<extra></extra>")
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
                          annotations=[dict(text=rec.score.profile, showarrow=False, font_size=16)])
        st.plotly_chart(fig, width="stretch")


def weights_vector(weights: dict) -> np.ndarray:
    """Weights in the fixed TICKERS order used by the return columns."""
    return np.array([weights[t] for t in pr.TICKERS])


def show_statistics(rec: pr.Recommendation, window: pd.DataFrame, rf_avg: float, rf_now: float) -> None:
    st.subheader("Expected return and risk (from historical data)")
    first, last = window.index[0], window.index[-1]
    st.caption(f"Based on {len(window)} monthly total returns, {first:%b %Y} to {last:%b %Y}. "
               "Estimates are illustrative, not forecasts.")
    if len(window) < MIN_MONTHS:
        st.warning(f"Only {len(window)} months of data are available; these estimates are very noisy.")

    w = weights_vector(rec.weights)
    s = fin.portfolio_summary(window, w, rf_avg)

    c1, c2, c3 = st.columns(3)
    c1.metric("Expected return (annual)", f"{s['expected_return']:.1%}",
              help="Weighted average of each ETF's annualized mean monthly return: w^T mu.")
    c2.metric("Volatility (annual)", f"{s['volatility']:.1%}",
              help="sqrt(w^T Sigma w) using the annualized covariance matrix.")
    c3.metric("Sharpe ratio", f"{s['sharpe']:.2f}",
              help="(Expected return - average T-bill rate) / volatility.")
    c4, c5, c6 = st.columns(3)
    c4.metric("Max drawdown", f"{s['max_drawdown']:.1%}", help="Worst peak-to-trough fall in the backtest.")
    c5.metric("Backtest CAGR", f"{s['cagr']:.1%}", help="Compound annual growth rate actually achieved.")
    c6.metric("$10,000 became", f"${s['wealth'].iloc[-1]:,.0f}")

    benefit = s["naive_volatility"] - s["volatility"]
    st.markdown(
        f"**Diversification:** a simple weighted average of the ETFs' volatilities would be "
        f"{s['naive_volatility']:.1%}. Using the covariance matrix gives {s['volatility']:.1%}: "
        f"imperfect correlation lowers risk by **{benefit:.1%} points**."
    )
    st.caption(f"Sharpe uses the average 3-month T-bill rate over the same window ({rf_avg:.2%}). "
               f"Current T-bill rate: {rf_now:.2%}.")

    with st.expander("Per-ETF statistics"):
        mu = fin.annualized_return(window)
        vols = fin.annualized_volatility(window)
        per_etf = pd.DataFrame({
            "Ticker": pr.TICKERS,
            "Your weight": w * 100,
            "Expected return": mu[pr.TICKERS].to_numpy() * 100,
            "Volatility": vols[pr.TICKERS].to_numpy() * 100,
            "Sharpe": [(m - rf_avg) / v if v > 0 else np.nan for m, v in zip(mu[pr.TICKERS], vols[pr.TICKERS])],
        })
        pct = st.column_config.NumberColumn(format="%.1f%%")
        st.dataframe(per_etf, hide_index=True, width="stretch",
                     column_config={"Your weight": pct, "Expected return": pct, "Volatility": pct,
                                    "Sharpe": st.column_config.NumberColumn(format="%.2f")})
        st.caption("BIL (T-bills) has almost no volatility, so its Sharpe ratio is not meaningful.")

    show_backtest(window, s["wealth"], rf_avg)


def show_backtest(window: pd.DataFrame, wealth: pd.Series, rf_avg: float) -> None:
    st.subheader("Historical backtest: growth of $10,000")
    fig = go.Figure()
    for name, base in pr.BASE_ALLOCATIONS.items():
        base_wealth = fin.growth_of_investment(window, weights_vector(base))
        fig.add_trace(go.Scatter(x=base_wealth.index, y=base_wealth, name=f"{name} (base)",
                                 line=dict(color=PROFILE_COLORS[name], width=1.5, dash="dot")))
    fig.add_trace(go.Scatter(x=wealth.index, y=wealth, name="Your portfolio",
                             line=dict(color="#1f4e9c", width=3)))
    fig.update_layout(yaxis_title="Portfolio value ($)", yaxis_tickprefix="$", yaxis_tickformat=",.0f",
                      hovermode="x unified", margin=dict(t=10, b=10, l=10, r=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    st.plotly_chart(fig, width="stretch")
    st.caption("Rebalanced monthly to the target weights, dividends reinvested, no fees or taxes. "
               "Dotted lines show the three base profiles for comparison.")


MC_PATHS, MC_SEED = 5_000, 42


def show_monte_carlo(rec: pr.Recommendation, window: pd.DataFrame, rf_now: float, settings: dict) -> None:
    years = int(rec.score.horizon_years)
    st.subheader(f"Monte Carlo projection over your {years}-year horizon")

    w = weights_vector(rec.weights)
    mu_forward = fin.forward_expected_returns(fin.annualized_return(window), pr.CASH_TICKER, rf_now)
    exp_ret = fin.portfolio_return(w, mu_forward[pr.TICKERS])
    vol = fin.portfolio_volatility(w, fin.annualized_covariance(window))
    geo = fin.expected_geometric_return(exp_ret, vol)

    paths = fin.monte_carlo_paths(exp_ret, vol, years, start_value=settings["start"],
                                  monthly_contribution=settings["contribution"], n_paths=MC_PATHS, seed=MC_SEED)
    bands = fin.percentile_bands(paths)  # p10 / p50 / p90
    x = bands.index / fin.PERIODS_PER_YEAR
    invested = settings["start"] + settings["contribution"] * years * fin.PERIODS_PER_YEAR

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=bands["p90"], name="90th percentile (good case)",
                             line=dict(color="#4a90d9", width=1)))
    fig.add_trace(go.Scatter(x=x, y=bands["p10"], name="10th percentile (bad case)", fill="tonexty",
                             fillcolor="rgba(74,144,217,0.2)", line=dict(color="#4a90d9", width=1)))
    fig.add_trace(go.Scatter(x=x, y=bands["p50"], name="Median", line=dict(color="#1f4e9c", width=3)))
    fig.add_trace(go.Scatter(x=[0, years], y=[settings["start"], invested], name="Amount invested",
                             line=dict(color="#9e9e9e", dash="dash")))
    fig.update_layout(xaxis_title="Years from today", yaxis_title="Portfolio value ($, nominal)",
                      yaxis_tickprefix="$", yaxis_tickformat=",.0f", hovermode="x unified",
                      margin=dict(t=10, b=10, l=10, r=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, traceorder="normal"))
    st.plotly_chart(fig, width="stretch")

    final = bands.iloc[-1]
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Bad case (10th pct.) in {years} yrs", f"${final['p10']:,.0f}")
    c2.metric("Median", f"${final['p50']:,.0f}")
    c3.metric("Good case (90th pct.)", f"${final['p90']:,.0f}")
    st.caption(
        f"{MC_PATHS:,} simulated paths (fixed random seed {MC_SEED}, so results are reproducible). Each month's return "
        f"is drawn from a normal distribution with mean {exp_ret:.1%}/12 and volatility {vol:.1%}/√12. "
        f"The expected return uses the historical average for every ETF except BIL (cash), which uses today's "
        f"T-bill rate ({rf_now:.2%}). Without contributions, the median grows at about {geo:.1%} a year: less than "
        f"the {exp_ret:.1%} arithmetic expected return, because volatility drags down compound growth "
        f"(≈ σ²/2). Values are nominal dollars, not adjusted for inflation."
    )


def show_risk_return(rec: pr.Recommendation, window: pd.DataFrame) -> None:
    st.subheader("Risk vs. return: ETFs, profiles and your portfolio")
    mu = fin.annualized_return(window)
    vols = fin.annualized_volatility(window)
    cov = fin.annualized_covariance(window)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=vols[pr.TICKERS] * 100, y=mu[pr.TICKERS] * 100, mode="markers+text",
                             text=pr.TICKERS, name="Individual ETFs",
                             # BND sits just under TIP, so put its label below the point.
                             textposition=["bottom center" if t == "BND" else "top center" for t in pr.TICKERS],
                             marker=dict(color="#9e9e9e", size=8)))
    for name, base in pr.BASE_ALLOCATIONS.items():
        w = weights_vector(base)
        fig.add_trace(go.Scatter(x=[fin.portfolio_volatility(w, cov) * 100],
                                 y=[fin.portfolio_return(w, mu[pr.TICKERS]) * 100],
                                 mode="markers+text", text=[name], textposition="top center", name=name,
                                 marker=dict(color=PROFILE_COLORS[name], size=14)))
    w = weights_vector(rec.weights)
    fig.add_trace(go.Scatter(x=[fin.portfolio_volatility(w, cov) * 100],
                             y=[fin.portfolio_return(w, mu[pr.TICKERS]) * 100],
                             mode="markers", name="Your portfolio",
                             marker=dict(color="#1f4e9c", size=20, symbol="star", line=dict(color="white", width=1))))
    fig.update_layout(xaxis_title="Volatility (annual %)", yaxis_title="Expected return (annual %)",
                      xaxis_ticksuffix="%", yaxis_ticksuffix="%", margin=dict(t=10, b=10, l=10, r=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    st.plotly_chart(fig, width="stretch")
    st.caption("Profiles sit to the left of a straight line between bonds and stocks: combining assets that "
               "aren't perfectly correlated gives less risk than the weighted average of their volatilities. "
               "Historical estimates for this lookback window, not forecasts.")


def show_analysis(rec: pr.Recommendation, settings: dict) -> None:
    """Load data (with fallbacks) and show statistics; never let a data problem crash the page."""
    st.sidebar.header("Data sources")
    prices_result = data.cached_prices(tuple(pr.TICKERS))
    rf_result = data.cached_risk_free()
    show_source("Prices", prices_result)
    show_source("Risk-free rate", rf_result)

    if prices_result.data is None:
        st.error("Historical prices are unavailable, so return and risk statistics can't be shown. "
                 "Your profile and allocation above are still valid. Details: " + prices_result.message)
        return
    try:
        window = fin.lookback_window(fin.monthly_returns(prices_result.data[pr.TICKERS]), settings["years"])
        if len(window) < 3:
            st.error("Not enough overlapping monthly data to compute statistics.")
            return
        rf_avg, rf_now = resolve_risk_free(rf_result, window)
        show_statistics(rec, window, rf_avg, rf_now)
        st.divider()
        show_monte_carlo(rec, window, rf_now, settings)
        st.divider()
        show_risk_return(rec, window)
    except Exception as e:  # last line of defence: show a message, never a traceback
        st.error(f"Something went wrong while computing statistics ({type(e).__name__}). "
                 "Try another lookback, or reload the page.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def main() -> None:
    st.title("📊 FIN471 Robo-Advisor")
    st.caption("Answer a few questions to see an illustrative diversified ETF portfolio. "
               "Everything updates as soon as you change an answer.")
    st.info(DISCLAIMER)

    horizon, answers = questionnaire()
    settings = analysis_settings()
    try:
        rec = pr.recommend(horizon, answers)
    except ValueError as e:
        st.error(f"Please check your inputs: {e}")
        st.stop()

    show_profile(rec)
    st.divider()
    show_allocation(rec)
    st.divider()
    show_analysis(rec, settings)

    st.divider()
    with st.expander("Limitations"):
        st.markdown("\n".join(f"- {item}" for item in LIMITATIONS))


main()
