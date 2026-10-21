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
PROFILE_COLORS = {"Conservative": "#2e8b57", "Moderate": "#e0a030", "Aggressive": "#8e6cc9"}
LOOKBACKS = {"5 years": 5, "10 years": 10, "Max common history": None}
RETURN_ASSUMPTIONS = ["Historical (default)", "Conservative adjustment"]
MIN_MONTHS = 24  # fewer monthly returns than this makes the estimates unreliable
MC_PATHS, MC_SEED = 5_000, 42

DISCLAIMER = (
    "**Educational illustration only - not investment advice.** This tool was built for a "
    "university finance course. It does not know your full financial situation, taxes, or goals, "
    "and past returns do not predict future results. Talk to a licensed professional before investing."
)


def _tickers_of(asset_type: str) -> str:
    return ", ".join(t for t in pr.TICKERS if pr.ASSET_TYPE[t] == asset_type)


def adjustment_summary() -> str:
    """Plain-English description of the Conservative adjustment, built from the constants."""
    a = pr.CONSERVATIVE_ADJUSTMENT
    return (f"equity ETFs ({_tickers_of('equity')}) {a['equity'] * 100:+.1f} points, "
            f"bond ETFs ({_tickers_of('bond')}) {a['bond'] * 100:+.1f} points, "
            f"cash ({_tickers_of('cash')}) unchanged")


# Shown in the "Methodology & Assumptions" section.
METHODOLOGY = [
    "**Profile:** score = horizon points (0-10) + five risk questions (0-4 each) = 0-30. "
    "0-12 Conservative, 13-21 Moderate, 22-30 Aggressive. A horizon under 3 years forces Conservative; "
    "3-5 years caps the profile at Moderate.",
    "**Allocation:** each profile has a fixed base mix of 7 ETFs. The horizon then tilts it by "
    "(horizon - 10 years) x 1 percentage point, capped at ±10, between the growth sleeve (stocks, REITs) "
    "and the defensive sleeve (bonds, cash). The score picks the profile; the tilt fine-tunes within it, "
    "and the cap means a tilt can never move a portfolio into another profile's range.",
    "**Data sources:** prices from Yahoo Finance via yfinance (fallbacks: Tiingo, the last saved copy, "
    "then a bundled educational sample); 3-month T-bill rate from FRED (series DTB3); live quotes "
    "from Finnhub (context only). The sidebar shows which source is in use.",
    "**Returns:** month-end dividend-adjusted prices (total returns) for 7 ETFs; monthly return "
    "r_t = P_t / P_(t-1) - 1. Only months where all 7 ETFs have data are used. The default lookback "
    "is 10 years (120 months); 5 years and the maximum common history (from mid-2013) are selectable.",
    "**Expected return:** mu_i = 12 x average monthly return (arithmetic); portfolio mu_p = w^T mu.",
    "**Volatility:** annualized covariance matrix Sigma = 12 x monthly sample covariance; "
    "sigma_p = sqrt(w^T Sigma w). This includes correlations, so it is lower than the weighted "
    "average of the ETFs' volatilities.",
    "**Sharpe ratio:** (mu_p - r_f) / sigma_p, where r_f is the average 3-month T-bill rate (FRED DTB3) "
    "over the same lookback window. Shown as n/a when volatility is below 1% (e.g. 100% T-bills), "
    "because dividing by almost zero gives a meaningless number.",
    "**Backtest:** $10,000 rebalanced monthly to the target weights, using actual historical returns. "
    "CAGR = (W_end / W_start)^(1/years) - 1; max drawdown = worst fall from a running peak.",
    "**Monte Carlo:** 5,000 paths of normally distributed monthly returns with mean mu_p/12 and "
    "volatility sigma_p/sqrt(12), fixed seed 42, showing 10th/50th/90th percentiles over your horizon. "
    "Cash (BIL) uses today's T-bill rate as its expected return. The median grows at about "
    "exp(mu_p - sigma_p^2/2) - 1 per year, below the arithmetic mu_p: this \"volatility drag\" is why "
    "compounding volatile returns grows money more slowly than the average return suggests.",
    "**Manual override:** custom weights must be 0% or more and total 100%; the portfolio is then "
    "labelled *Custom* and every statistic and chart uses it.",
    "**Return assumptions:** *Historical (default)* uses the lookback averages as they are. "
    f"*Conservative adjustment* lowers expected returns: {adjustment_summary()}. It applies to the "
    "expected return, Sharpe ratio, risk/return chart and Monte Carlo, but **not** to the historical "
    "backtest, CAGR or drawdown, which always show what actually happened.",
]

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
    "**No costs or taxes.** ETF expense ratios, trading costs, taxes and account types (401(k), IRA, "
    "taxable) are ignored.",
    "**A simplified questionnaire.** Five questions and a horizon are not a regulatory suitability "
    "assessment; real advisors also consider income, debts, goals and liquidity needs.",
    "**Data caveats.** yfinance is an unofficial Yahoo Finance scraper; the bundled sample can be out "
    "of date; DTB3 is quoted on a discount basis, slightly below a bond-equivalent yield; live quotes "
    "show the last trade and are not used in any calculation.",
]


# ---------------------------------------------------------------------------
# Sidebar
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
    assumption = st.sidebar.radio(
        "Return assumptions", RETURN_ASSUMPTIONS, index=0, key="return_assumption",
        help=f"Conservative adjustment: {adjustment_summary()}. Affects expected return, Sharpe and the "
             "Monte Carlo, not the historical backtest.",
    )
    start = st.sidebar.number_input(
        "Starting amount ($)", min_value=100, max_value=10_000_000, value=10_000, step=1_000, key="start_amount",
        help="Amount invested today in the Monte Carlo projection.",
    )
    contribution = st.sidebar.number_input(
        "Monthly contribution ($)", min_value=0, max_value=100_000, value=0, step=100, key="contribution",
        help="Added at the end of every month in the projection (optional).",
    )
    return {"years": LOOKBACKS[choice], "conservative": assumption == RETURN_ASSUMPTIONS[1],
            "start": float(start), "contribution": float(contribution)}


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
# Questionnaire result
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


# ---------------------------------------------------------------------------
# Manual override
# ---------------------------------------------------------------------------
def _weight_key(ticker: str) -> str:
    return f"w_{ticker}"


def _load_weight_inputs(weights_pct: dict) -> None:
    """Put percentages into the per-ETF number inputs (via their session-state keys)."""
    for t in pr.TICKERS:
        st.session_state[_weight_key(t)] = float(weights_pct[t])


def _current_weight_inputs() -> dict:
    return {t: st.session_state[_weight_key(t)] for t in pr.TICKERS}


def _on_toggle(recommended: dict) -> None:
    if st.session_state.override:  # just switched on: start from the recommendation
        _load_weight_inputs(pr.normalize_to_percent(recommended))


def _normalize() -> None:
    _load_weight_inputs(pr.normalize_to_percent(_current_weight_inputs()))


def _reset(recommended: dict) -> None:
    _load_weight_inputs(pr.normalize_to_percent(recommended))


def choose_weights(rec: pr.Recommendation) -> tuple[dict | None, str]:
    """Return (weights as fractions, label). Weights is None while custom weights are unusable."""
    st.toggle("Customize weights manually", key="override", on_change=_on_toggle, args=(rec.weights,),
              help="Type your own weights to see how the statistics change. Your questionnaire result is kept.")
    if not st.session_state.override:
        return rec.weights, rec.score.profile

    if any(_weight_key(t) not in st.session_state for t in pr.TICKERS):
        _load_weight_inputs(pr.normalize_to_percent(rec.weights))
    # One input per ETF in two columns. min 0 means negative weights can't be entered;
    # check_custom_weights() still rejects them as a second line of defence.
    columns = st.columns(2)
    for i, t in enumerate(pr.TICKERS):
        columns[i % 2].number_input(f"{t} (%) – {pr.ETF_INFO[t][1]}", min_value=0.0, max_value=100.0,
                                    step=1.0, format="%.1f", key=_weight_key(t))
    weights_pct = _current_weight_inputs()
    total = sum(weights_pct.values())
    st.caption(f"Total: **{total:.1f}%** (must be 100%)")
    status, message = pr.check_custom_weights(weights_pct)

    if status == "not_100":
        example = 30 / total * 100
        st.warning(f"⚠️ **{message}** Statistics are paused until the weights total 100%. Fix the numbers, "
                   f"or click **Normalize to 100%** to scale every weight proportionally "
                   f"(for example, 30% of a {total:.1f}% total becomes {example:.1f}%).")
    elif status == "invalid":
        st.error(f"⛔ {message} Statistics are paused until this is fixed.")
    left, right = st.columns(2)  # buttons below the message
    if status == "not_100":
        left.button("Normalize to 100%", on_click=_normalize, key="normalize")
    right.button("Reset to recommended", on_click=_reset, args=(rec.weights,), key="reset_weights")

    if status != "ok":
        return None, "Custom"
    return pr.normalize_weights(weights_pct), "Custom"


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------
def allocation_table(weights: dict, compare: dict, compare_label: str) -> pd.DataFrame:
    rows = []
    for t in pr.TICKERS:
        name, asset_class = pr.ETF_INFO[t]
        # Weights first so they stay visible on narrow screens; long fund name last.
        rows.append({
            "Ticker": t, "Your weight": weights[t], compare_label: compare[t],
            "Asset class": asset_class, "Sleeve": "Growth" if t in pr.GROWTH else "Defensive",
            "ETF": name,
        })
    return pd.DataFrame(rows)


def show_allocation(rec: pr.Recommendation, weights: dict, label: str) -> None:
    custom = label == "Custom"
    if custom:
        growth = pr.growth_share(weights)
        st.caption(f"**Custom portfolio** ({growth:.0%} growth / {1 - growth:.0%} defensive). Your questionnaire "
                   f"result ({rec.score.profile}) is shown in the *Recommended* column for comparison.")
        table = allocation_table(weights, rec.weights, "Recommended")
    else:
        tilt = rec.tilt
        direction = "toward growth" if tilt > 0 else "toward defensive assets" if tilt < 0 else "no shift"
        st.caption(
            f"Starting from the {rec.score.profile} base mix, your {rec.score.horizon_years}-year horizon applies a "
            f"**{tilt:+.0%} tilt ({direction})**: (horizon - 10 yrs) x 1 percentage point per year, capped at ±10. "
            "The shift is spread proportionally inside each sleeve, so the mix of US vs international "
            "stocks (and of the bond funds) stays the same."
        )
        table = allocation_table(weights, rec.base_weights, "Base weight")

    compare_col = table.columns[2]
    left, right = st.columns([3, 2])
    with left:
        shown = table.assign(**{c: table[c] * 100 for c in ("Your weight", compare_col)})
        pct = st.column_config.NumberColumn(format="%.1f%%")
        st.dataframe(shown, hide_index=True, width="stretch",
                     column_config={"Your weight": pct, compare_col: pct})
    with right:
        chart_data = table[table["Your weight"] > 0.0005]
        fig = px.pie(chart_data, names="Ticker", values="Your weight", hole=0.55,
                     color="Ticker", color_discrete_map=ETF_COLORS, custom_data=["Asset class"])
        # One decimal place, matching the table.
        fig.update_traces(texttemplate="%{label}<br>%{percent:.1%}", sort=False,
                          hovertemplate="%{label}: %{percent:.1%}<br>%{customdata[0]}<extra></extra>")
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
                          annotations=[dict(text=label, showarrow=False, font_size=16)])
        st.plotly_chart(fig, width="stretch")


def show_quotes(weights: dict) -> None:
    """Live Finnhub quotes for the ETFs in the current allocation. Never blocks the rest of the page."""
    st.markdown("**Live market quotes (Finnhub)**")
    held = tuple(t for t in pr.TICKERS if weights.get(t, 0) > 0.0005)
    try:
        result = data.cached_quotes(held)
    except Exception:  # defensive: a quote problem must never break the page
        result = data.DataResult(None, "error", "Live quotes unavailable right now.")
    if result.data is None:
        st.caption(f"ℹ️ {result.message} The rest of the app works without quotes.")
        return

    quotes = result.data.reset_index()
    as_of = pd.to_datetime(quotes["As of"]).dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    table = pd.DataFrame({
        "Ticker": quotes["Ticker"],
        "Price": quotes["Price"],
        "Day change %": quotes["Change %"],
        "Last trade (ET)": as_of.dt.strftime("%b %d, %H:%M"),
    })
    st.dataframe(table, hide_index=True, width="content",
                 column_config={"Price": st.column_config.NumberColumn(format="$%.2f"),
                                "Day change %": st.column_config.NumberColumn(format="%+.2f%%")})
    fetched = result.fetched_at.tz_convert("America/New_York").strftime("%b %d, %Y %H:%M:%S ET")
    extra = f" {result.message.replace('Live quotes from Finnhub.', '').strip()}" if "unavailable" in result.message else ""
    st.caption(f"Fetched {fetched}; refreshed at most every {data.QUOTE_TTL_SECONDS} seconds. "
               f"Quotes are for context only; the statistics below use monthly historical data.{extra}")


# ---------------------------------------------------------------------------
# Statistics and charts
# ---------------------------------------------------------------------------
def weights_vector(weights: dict) -> np.ndarray:
    """Weights in the fixed TICKERS order used by the return columns."""
    return np.array([weights[t] for t in pr.TICKERS])


def fmt_money(value: float) -> str:
    """$12,345 below a million, then $12.3M / $1.23B so metrics never get cut off mid-number."""
    if value >= 1e9:
        return f"${value / 1e9:,.2f}B"
    if value >= 1e6:
        return f"${value / 1e6:,.1f}M"
    return f"${value:,.0f}"


def _sharpe_text(value: float) -> str:
    return "n/a" if np.isnan(value) else f"{value:.2f}"


def money_scale(max_value: float) -> tuple[float, str, str, str]:
    """Pick readable dollar units for a chart axis: (divisor, tick suffix, axis unit, number format).

    $10,000,000 starting amounts would otherwise give long labels like $250,000,000.
    """
    if max_value >= 1e9:
        return 1e9, "B", "$ billions", ",.1~f"
    if max_value >= 1e6:
        return 1e6, "M", "$ millions", ",.1~f"
    return 1.0, "", "$", ",.0f"


def show_statistics(weights: dict, label: str, window: pd.DataFrame, mu_expected: pd.Series,
                    rf_avg: float, rf_now: float, conservative: bool) -> None:
    st.subheader(f"Expected return and risk: {label} portfolio")
    first, last = window.index[0], window.index[-1]
    st.caption(f"Based on {len(window)} monthly total returns, {first:%b %Y} to {last:%b %Y}. "
               "Estimates are illustrative, not forecasts.")
    if len(window) < MIN_MONTHS:
        st.warning(f"Only {len(window)} months of data are available; these estimates are very noisy.")

    w = weights_vector(weights)
    mu_hist = fin.annualized_return(window)
    s = fin.portfolio_summary(window, w, rf_avg, expected_returns=mu_expected)
    hist_return = fin.portfolio_return(w, mu_hist[pr.TICKERS])
    if conservative:
        st.info(f"**Conservative adjustment on:** {adjustment_summary()}. For this portfolio that lowers the "
                f"expected return by **{(hist_return - s['expected_return']) * 100:.2f} points** "
                f"(from {hist_return:.1%} to {s['expected_return']:.1%}). Applied to expected return, Sharpe ratio, "
                "the risk/return chart and the Monte Carlo; the historical backtest (CAGR, drawdown, growth "
                "of $10,000) still uses actual returns.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Expected return (annual)", f"{s['expected_return']:.1%}",
              delta=f"{(s['expected_return'] - hist_return) * 100:+.2f} pts vs historical" if conservative else None,
              delta_color="off",
              help="Weighted average of each ETF's annualized mean monthly return: w^T mu.")
    c2.metric("Volatility (annual)", f"{s['volatility']:.1%}",
              help="sqrt(w^T Sigma w) using the annualized covariance matrix.")
    sharpe_na = np.isnan(s["sharpe"])
    c3.metric("Sharpe ratio", "n/a" if sharpe_na else f"{s['sharpe']:.2f}",
              help=(f"Not shown: volatility is below {fin.MIN_VOLATILITY_FOR_SHARPE:.0%}, so the ratio would divide "
                    "by almost zero." if sharpe_na else "(Expected return - average T-bill rate) / volatility."))
    c4, c5, c6 = st.columns(3)
    c4.metric("Max drawdown", f"{s['max_drawdown']:.1%}", help="Worst peak-to-trough fall in the backtest.")
    c5.metric("Backtest CAGR", f"{s['cagr']:.1%}", help="Compound annual growth rate actually achieved.")
    c6.metric("$10,000 became", f"${s['wealth'].iloc[-1]:,.0f}")

    benefit = s["naive_volatility"] - s["volatility"]
    if benefit < 0.0005:  # e.g. 100% in one ETF
        st.markdown(f"**Diversification:** none here. With everything in one ETF, portfolio volatility equals "
                    f"that ETF's volatility ({s['volatility']:.1%}); mixing imperfectly correlated ETFs would lower it.")
    else:
        st.markdown(
            f"**Diversification:** a simple weighted average of the ETFs' volatilities would be "
            f"{s['naive_volatility']:.1%}. Using the covariance matrix gives {s['volatility']:.1%}: "
            f"imperfect correlation lowers risk by **{benefit:.1%} points**."
        )
    sharpe_note = (f" **Sharpe ratio n/a:** portfolio volatility is only {s['volatility']:.2%} (below "
                   f"{fin.MIN_VOLATILITY_FOR_SHARPE:.0%}), so dividing by it would give a huge, meaningless number."
                   if sharpe_na else "")
    st.caption(f"Sharpe uses the average 3-month T-bill rate over the same window ({rf_avg:.2%}). "
               f"Current T-bill rate: {rf_now:.2%}.{sharpe_note}")

    with st.expander("Per-ETF statistics"):
        vols = fin.annualized_volatility(window)
        exp = mu_expected[pr.TICKERS]
        per_etf = pd.DataFrame({
            "Ticker": pr.TICKERS,
            "Your weight": w * 100,
            "Historical return": mu_hist[pr.TICKERS].to_numpy() * 100,
            "Adjustment": (exp - mu_hist[pr.TICKERS]).to_numpy() * 100,
            "Expected return used": exp.to_numpy() * 100,
            "Volatility": vols[pr.TICKERS].to_numpy() * 100,
            "Sharpe": [_sharpe_text(fin.sharpe_ratio(m, v, rf_avg, min_volatility=fin.MIN_VOLATILITY_FOR_SHARPE))
                       for m, v in zip(exp, vols[pr.TICKERS])],
        })
        pct = st.column_config.NumberColumn(format="%.1f%%")
        st.dataframe(per_etf, hide_index=True, width="stretch",
                     column_config={"Your weight": pct, "Historical return": pct, "Expected return used": pct,
                                    "Adjustment": st.column_config.NumberColumn(format="%+.1f pts"),
                                    "Volatility": pct})
        st.caption(f"Sharpe is n/a when volatility is below {fin.MIN_VOLATILITY_FOR_SHARPE:.0%} "
                   "(BIL, T-bills): dividing by almost zero isn't meaningful.")

    show_backtest(window, s["wealth"], label)


def show_backtest(window: pd.DataFrame, wealth: pd.Series, label: str) -> None:
    st.subheader("Historical backtest: growth of $10,000")
    fig = go.Figure()
    for name, base in pr.BASE_ALLOCATIONS.items():
        base_wealth = fin.growth_of_investment(window, weights_vector(base))
        fig.add_trace(go.Scatter(x=base_wealth.index, y=base_wealth, name=f"{name} (base)",
                                 line=dict(color=PROFILE_COLORS[name], width=1.5, dash="dot")))
    fig.add_trace(go.Scatter(x=wealth.index, y=wealth, name=f"Your portfolio ({label})",
                             line=dict(color="#1f4e9c", width=3)))
    fig.update_layout(yaxis_title="Portfolio value ($)", yaxis_tickprefix="$", yaxis_tickformat=",.0f",
                      hovermode="x unified", margin=dict(t=10, b=10, l=10, r=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    st.plotly_chart(fig, width="stretch")
    st.caption("Actual historical returns (never adjusted), rebalanced monthly to the target weights, dividends "
               "reinvested, no fees or taxes. Dotted lines show the three base profiles for comparison.")


def show_monte_carlo(weights: dict, label: str, years: int, window: pd.DataFrame, mu_expected: pd.Series,
                     rf_now: float, settings: dict) -> None:
    st.subheader(f"Monte Carlo projection: {label} portfolio over your {years}-year horizon")

    w = weights_vector(weights)
    mu_forward = fin.forward_expected_returns(mu_expected, pr.CASH_TICKER, rf_now)
    exp_ret = fin.portfolio_return(w, mu_forward[pr.TICKERS])
    vol = fin.portfolio_volatility(w, fin.annualized_covariance(window))
    geo = fin.expected_geometric_return(exp_ret, vol)

    paths = fin.monte_carlo_paths(exp_ret, vol, years, start_value=settings["start"],
                                  monthly_contribution=settings["contribution"], n_paths=MC_PATHS, seed=MC_SEED)
    bands = fin.percentile_bands(paths)  # p10 / p50 / p90
    x = bands.index / fin.PERIODS_PER_YEAR
    invested = settings["start"] + settings["contribution"] * years * fin.PERIODS_PER_YEAR

    div, suffix, unit, num = money_scale(max(bands["p90"].max(), invested))
    hover = f"$%{{y:{num}}}{suffix}"
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=bands["p90"] / div, name="90th percentile (good case)", hovertemplate=hover,
                             line=dict(color="#4a90d9", width=1)))
    fig.add_trace(go.Scatter(x=x, y=bands["p10"] / div, name="10th percentile (bad case)", fill="tonexty",
                             hovertemplate=hover, fillcolor="rgba(74,144,217,0.2)", line=dict(color="#4a90d9", width=1)))
    fig.add_trace(go.Scatter(x=x, y=bands["p50"] / div, name="Median", hovertemplate=hover,
                             line=dict(color="#1f4e9c", width=3)))
    fig.add_trace(go.Scatter(x=[0, years], y=[settings["start"] / div, invested / div], name="Amount invested",
                             hovertemplate=hover, line=dict(color="#9e9e9e", dash="dash")))
    fig.update_layout(xaxis_title="Years from today", yaxis_title=f"Portfolio value ({unit}, nominal)",
                      yaxis_tickprefix="$", yaxis_ticksuffix=suffix, yaxis_tickformat=num, yaxis_rangemode="tozero",
                      hovermode="x unified", margin=dict(t=10, b=10, l=10, r=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, traceorder="normal"))
    st.plotly_chart(fig, width="stretch")

    final = bands.iloc[-1]
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Bad case (10th pct.) in {years} {'yr' if years == 1 else 'yrs'}", fmt_money(final["p10"]))
    c2.metric("Median", fmt_money(final["p50"]))
    c3.metric("Good case (90th pct.)", fmt_money(final["p90"]))
    basis = "historical average (with the Conservative adjustment)" if settings["conservative"] else "historical average"
    st.caption(
        f"{MC_PATHS:,} simulated paths (fixed random seed {MC_SEED}, so results are reproducible). Each month's return "
        f"is drawn from a normal distribution with mean {exp_ret:.1%}/12 and volatility {vol:.1%}/√12. "
        f"The expected return uses the {basis} for every ETF except BIL (cash), which uses today's "
        f"T-bill rate ({rf_now:.2%}). Without contributions, the median grows at about {geo:.1%} a year: less than "
        f"the {exp_ret:.1%} arithmetic expected return, because volatility drags down compound growth "
        f"(≈ σ²/2). Values are nominal dollars, not adjusted for inflation."
    )


def show_risk_return(weights: dict, label: str, window: pd.DataFrame, mu_expected: pd.Series,
                     conservative: bool) -> None:
    st.subheader("Risk vs. return: ETFs, profiles and your portfolio")
    mu = mu_expected[pr.TICKERS]
    vols = fin.annualized_volatility(window)
    cov = fin.annualized_covariance(window)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=vols[pr.TICKERS] * 100, y=mu * 100, mode="markers+text",
                             text=pr.TICKERS, name="Individual ETFs",
                             # BND sits just under TIP, so put its label below the point.
                             textposition=["bottom center" if t == "BND" else "top center" for t in pr.TICKERS],
                             marker=dict(color="#9e9e9e", size=8)))
    for name, base in pr.BASE_ALLOCATIONS.items():
        w = weights_vector(base)
        fig.add_trace(go.Scatter(x=[fin.portfolio_volatility(w, cov) * 100], y=[fin.portfolio_return(w, mu) * 100],
                                 mode="markers+text", text=[name], textposition="top center", name=name,
                                 marker=dict(color=PROFILE_COLORS[name], size=14)))
    w = weights_vector(weights)
    fig.add_trace(go.Scatter(x=[fin.portfolio_volatility(w, cov) * 100], y=[fin.portfolio_return(w, mu) * 100],
                             mode="markers", name=f"Your portfolio ({label})",
                             marker=dict(color="#1f4e9c", size=20, symbol="star", line=dict(color="white", width=1))))
    fig.update_layout(xaxis_title="Volatility (annual %)", yaxis_title="Expected return (annual %)",
                      xaxis_ticksuffix="%", yaxis_ticksuffix="%", margin=dict(t=10, b=10, l=10, r=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    st.plotly_chart(fig, width="stretch")
    note = " Expected returns include the Conservative adjustment." if conservative else ""
    st.caption("Profiles sit to the left of a straight line between bonds and stocks: combining assets that "
               "aren't perfectly correlated gives less risk than the weighted average of their volatilities. "
               "Historical estimates for this lookback window, not forecasts." + note)


def show_analysis(weights: dict | None, label: str, years: int, settings: dict) -> None:
    """Load data (with fallbacks) and show statistics; never let a data problem crash the page."""
    st.sidebar.header("Data sources")
    prices_result = data.cached_prices(tuple(pr.TICKERS))
    rf_result = data.cached_risk_free()
    show_source("Prices", prices_result)
    show_source("Risk-free rate", rf_result)

    if weights is None:
        st.info("Statistics and charts are paused until your custom weights are valid and total 100% (see above).")
        return
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
        mu_expected = fin.adjust_expected_returns(fin.annualized_return(window),
                                                  pr.return_adjustments(settings["conservative"]))
        show_statistics(weights, label, window, mu_expected, rf_avg, rf_now, settings["conservative"])
        st.divider()
        show_monte_carlo(weights, label, years, window, mu_expected, rf_now, settings)
        st.divider()
        show_risk_return(weights, label, window, mu_expected, settings["conservative"])
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

    st.subheader("Your ETF allocation")
    weights, label = choose_weights(rec)
    if weights is not None:
        show_allocation(rec, weights, label)
        show_quotes(weights)
    st.divider()
    show_analysis(weights, label, int(rec.score.horizon_years), settings)

    st.divider()
    with st.expander("Methodology & Assumptions"):
        st.markdown("\n".join(f"- {item}" for item in METHODOLOGY))
    with st.expander("Limitations"):
        st.markdown("\n".join(f"- {item}" for item in LIMITATIONS))


main()
