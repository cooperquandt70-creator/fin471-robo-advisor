# FIN471 Robo-Advisor

> **Draft:** the remaining sections (features, APIs, formulas, AI usage, limitations, screenshots)
> are completed in milestone 9. This draft currently covers running the app and testing.

An educational Streamlit robo-advisor for FIN471 (Project 4). It scores your investment horizon and
risk tolerance, classifies you as Conservative, Moderate or Aggressive, recommends a diversified
7-ETF allocation, and estimates return and risk from real historical data.
**It is an educational illustration, not investment advice.**

## Quick start

```bash
pip install -r requirements.txt
copy .env.example .env        # then paste your free API keys into .env
streamlit run app.py
```

## Testing

Run the whole suite (about 15 seconds, fully offline: every network call is mocked, so results
don't depend on Yahoo, FRED or Tiingo being up):

```bash
python -m pytest
```

**254 tests** in four files:

| File | What it checks |
|---|---|
| `tests/test_finance.py` | Every formula with hand-checkable numbers. For example, 20% and 10% volatility, ρ = 0, 50/50 weights gives σ_p = 0.1118, not the 0.15 weighted average. The Monte Carlo median grows at exp(μ − σ²/2) − 1. |
| `tests/test_profiles.py` | Scoring, cut-offs, safety caps, horizon tilt, weight validation. The 25- vs 60-year-old example. |
| `tests/test_data.py` | The fallback chain (yfinance → Tiingo → saved copy → bundled sample), HTTP errors mapped to plain messages, API keys never leaking into messages. |
| `tests/test_app.py` | Runs the real Streamlit app headlessly (`streamlit.testing.AppTest`) and checks what a user would see. |

Live APIs can be checked separately with your own keys: `python scripts/check_apis.py`.
Add `--bad-key` to see the error handling with deliberately invalid keys.

### Robustness pass (milestone 8)

Each case has an automated test in `tests/test_app.py` (and unit tests where relevant). The
network cases were also run for real, outside pytest, against the live APIs.

| # | Case | How it was tested | Result |
|---|---|---|---|
| 1 | **100% BIL** (cash, near-zero volatility) | AppTest + unit tests | Volatility is 0.56%. Sharpe shows **"n/a"** with the reason "volatility below 1%, so dividing by it would give a huge, meaningless number". No division by zero. For this window the unguarded value would have been −0.29, but with a 0.56% denominator it swings wildly (about −3.0 using today's T-bill rate). The Monte Carlo still runs. |
| 2a | **100% in one ETF** (VTI, VNQ, BND tested) | AppTest | All statistics and all 4 charts work. The diversification note says "none here: with everything in one ETF, portfolio volatility equals that ETF's volatility". 100% VTI: 15.0% expected return, 15.8% volatility, Sharpe 0.80, max drawdown −24.8%. |
| 2b | **All weights 0** | AppTest + unit test | Error: "All weights are zero. Give at least one ETF a positive weight." Statistics pause with a message. No Normalize button appears, since there's nothing to scale. No crash. |
| 3 | **1-year horizon** in the Monte Carlo | AppTest + unit test | 12-month projection. Labels read "1-year horizon" and "in 1 yr" (grammar fixed). 10th < median < 90th percentile. |
| 4a | **No `.env` file** | AppTest (keys removed) + **real run** of a copy with no `.env` | Prices load live from yfinance (no key needed). The T-bill rate falls back to the bundled sample, with the badge "No FRED_API_KEY in .env". All statistics shown. |
| 4b | **Bad API keys** | AppTest (mocked HTTP 400/401) + **real run** with invalid keys + `check_apis.py --bad-key` | Badges: "FRED rejected the request (HTTP 400): the API key is probably invalid" and "Tiingo rejected the request (HTTP 401)…". Falls back to the saved copy or sample. Keys are never displayed. |
| 4c | **No network** | AppTest (mocked) + **real run** with all traffic sent to a dead proxy | Prices use the last saved copy, or the bundled educational sample when there is no saved copy (both verified for real). Badges say "Could not connect to FRED/Tiingo". All 4 charts are still shown. **Fixed:** the badge said "possibly rate-limited" when the network was down, and yfinance printed misleading "possibly delisted" lines to the console. |
| 4d | **yfinance rate-limited** | AppTest + unit test with a mocked `YFRateLimitError` (it can't be triggered on demand) | Tiingo takes over: "Live prices from Tiingo, because yfinance was unavailable: Yahoo Finance rate limit reached". Without a Tiingo key, the bundled sample is used with the same explanation. |
| 5 | **$0 monthly contribution, $10,000,000 start** | AppTest + checked in the browser | The Monte Carlo axis switches to "$ millions" ($0M to $500M), and the "amount invested" line is flat. **Fixed:** full numbers like "$92,117,…" were cut off in narrow columns and looked like $92 thousand; metrics now show "$92.1M / $208.1M / $485.8M". |

Also covered by earlier milestones' tests:
- **Ages 64, 65, 66, 80 and 90:** the horizon is never 0 or negative (minimum 1 year).
- **Weights:** negative weights are blocked (inputs have a minimum of 0) and also rejected in code. Weights that don't total 100% get a warning, and nothing is normalized until you click.
- **Data failures:** if every price source fails, the page shows an error but keeps your profile and allocation. If FRED is down, you can type a risk-free rate yourself.
