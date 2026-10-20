"""
app.py - Streamlit user interface for the FIN471 robo-advisor.

UI only: scoring and allocations come from profiles.py, the math from
finance.py, and all API calls from data.py.

Run with:  streamlit run app.py
"""

import pandas as pd
import plotly.express as px
import streamlit as st

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
]

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
        fig.update_traces(textinfo="label+percent", sort=False,
                          hovertemplate="%{label}: %{percent}<br>%{customdata[0]}<extra></extra>")
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
                          annotations=[dict(text=rec.score.profile, showarrow=False, font_size=16)])
        st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def main() -> None:
    st.title("📊 FIN471 Robo-Advisor")
    st.caption("Answer a few questions to see an illustrative diversified ETF portfolio. "
               "Everything updates as soon as you change an answer.")
    st.info(DISCLAIMER)

    horizon, answers = questionnaire()
    try:
        rec = pr.recommend(horizon, answers)
    except ValueError as e:
        st.error(f"Please check your inputs: {e}")
        st.stop()

    show_profile(rec)
    st.divider()
    show_allocation(rec)

    st.divider()
    with st.expander("Limitations"):
        st.markdown("\n".join(f"- {item}" for item in LIMITATIONS))


main()
