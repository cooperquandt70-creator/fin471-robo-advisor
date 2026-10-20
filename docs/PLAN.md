# FIN471 Project 4 â€” AI Robo-Advisor: Build Plan

## Context
FIN471 Project 4 is an educational Streamlit robo-advisor. It scores a user's horizon and risk tolerance, classifies them as Conservative, Moderate or Aggressive, and recommends a diversified ETF mix. It also computes return, risk, Sharpe ratio, drawdown and a Monte Carlo projection from real historical data, and updates live as inputs change. The constraints are free API tiers only, reproducibility for other students (clone, add a .env, pip install, streamlit run), an app that never crashes, and a set of grading deliverables (README, AI-usage log, screenshots). The folder `C:\dev\fin471-robo-advisor` is empty and is not a git repo yet.

**Decisions confirmed by the user:** yfinance as the primary price source with Tiingo and a bundled-snapshot fallback; a 10-year monthly lookback (switchable); a Sharpe ratio using the average DTB3 over the lookback; Finnhub used for a live quote panel.

---

## Step 0 â€” Free-tier verification (checked 2026-10-20)

| Source | Works on free tier | Does NOT work / caveats |
|---|---|---|
| **Finnhub** (official swagger.json) | `/quote` (real-time US quote, works for US-listed ETFs), `/search`, `/stock/profile2`, `/stock/metric`, `/company-news`, `/stock/market-status`. Free limit is 60 calls/min. | `/stock/candle` is flagged **"Premium Access Required"** (your belief is confirmed). `/etf/profile` and `/etf/holdings` are flagged **"Premium required."** `/etf/sector`, `/etf/country` and `/etf/allocation` are **premium** too. |
| **yfinance 1.7.0** (PyPI, Aug 2026) | No key needed. Full daily or monthly adjusted history for all ETFs. | Unofficial scraper. Yahoo terms say "personal use only". Frequent `YFRateLimitError` reports, so it needs caching and a fallback. |
| **Tiingo** (pricing page) | Free key gives EOD adjusted prices with 30+ years of history: 50 req/hr, 1,000/day, 500 unique symbols/mo. | License is "Internal Use Only", which is fine for a class demo; noted in the README. |
| **Alpha Vantage** (docs) | `TIME_SERIES_MONTHLY_ADJUSTED` and `WEEKLY_ADJUSTED` are free. | Only 25 requests/day. `DAILY_ADJUSTED` and `outputsize=full` are premium. Not used. |
| **FRED** | Free key. `series/observations` with `series_id=DTB3` and `file_type=json` works. | DTB3 is quoted on a discount basis (DGS3MO is the bond-equivalent alternative); noted as a limitation. |

**Recommendation:** use yfinance first, then Tiingo, then a bundled CSV snapshot. Finnhub `/quote` covers the required real external financial API. FRED DTB3 supplies the risk-free rate. Milestone 3 includes `scripts/check_apis.py` to re-confirm all of this live with real keys, since I had no keys to test with.

---

## ETF universe (7 ETFs, low cost, each with history through the full 10-year window)
| Ticker | Asset class | Role |
|---|---|---|
| VTI | US total stock market | Core growth |
| VXUS | International stocks (ex-US) | Global diversification |
| VNQ | US REITs | Real-asset diversifier |
| BND | US aggregate bonds | Core ballast |
| BNDX | International bonds (USD-hedged) | Bond diversification |
| TIP | US TIPS | Inflation protection |
| BIL | 1â€“3 month T-bills | Cash-like / liquidity |

## Base allocations (before the horizon tilt)
| | VTI | VXUS | VNQ | BND | BNDX | TIP | BIL | Growth / Defensive |
|---|---|---|---|---|---|---|---|---|
| Conservative | 18 | 8 | 4 | 35 | 10 | 15 | 10 | 30 / 70 |
| Moderate | 36 | 18 | 6 | 22 | 8 | 6 | 4 | 60 / 40 |
| Aggressive | 50 | 27 | 8 | 10 | 3 | 2 | 0 | 85 / 15 |

**Reasoning:**
- US to international stock is about 2:1, a deliberate home bias below the global market-cap weight of roughly 60/40.
- REITs stay small (4â€“8%).
- Conservative holds more TIPS and cash for inflation protection and liquidity.
- Aggressive keeps a small bond sleeve to dampen drawdowns.

**Horizon tilt (so horizon shifts the allocation, not just the score):** tilt = clip((horizon âˆ’ 10 yrs) Ã— 1%, âˆ’10%, +10%). The tilt moves weight from the defensive sleeve to the growth sleeve and keeps the proportions inside each sleeve unchanged. Growth is bounded between 20% and 95%.

**Why horizon appears in both the score and the tilt:**
- They do different jobs. The **score sets the profile**: horizon is one input to the coarse bucket (Conservative, Moderate or Aggressive), alongside willingness to take risk.
- The **tilt adjusts within the profile**: it fine-tunes the stock/bond split continuously.
- Without the tilt, a 25-year-old and a 45-year-old who land in the same bucket would get identical portfolios, and a one-point score change would cause a jump at each cut-off.
- The tilt is capped at Â±10 pp, so it can never turn one profile into another. A Conservative portfolio's growth share stays well below Moderate's base.

## Questionnaire scoring (`profiles.py`, fully transparent)
- **Age and horizon:** age is entered, and the horizon defaults to 65 âˆ’ age but can be edited (1â€“40 yrs). Horizon points: <3 yrs = 0, 3â€“5 = 2, 6â€“10 = 5, 11â€“20 = 8, >20 = 10.
- **Five risk questions scored 0â€“4 each (0â€“20 total):**
  1. Reaction to a 20% drop
  2. Primary goal (preserve, income, balanced, growth, max growth)
  3. Investing experience
  4. Income stability and emergency fund
  5. Gain/loss trade-off choice
- **Total 0â€“30:** 0â€“12 is Conservative, 13â€“21 is Moderate, 22â€“30 is Aggressive.
- **Safety caps:** a horizon under 3 years forces Conservative, and 3â€“5 years caps the profile at Moderate.
- **UI:** a points breakdown table plus a plain-English "why you landed here" sentence, including any cap that applied.
- **Example check (all-middle answers, 10 pts):** a 25-year-old (40-yr horizon) gets 20 points, which is Moderate with a +10% growth tilt, for about 70/30. A 60-year-old (5-yr horizon) gets 12 points, which is Conservative with a âˆ’5% tilt, for about 25/75. Covered by a pytest.

## Formulas (`finance.py`) â€” monthly total returns from adjusted close prices, 10-yr lookback (5 yr and max selectable)
- Monthly return: r_t = P_t / P_{tâˆ’1} âˆ’ 1
- Expected annual return per ETF: Î¼_i = 12 Â· mean(r_i), arithmetic. CAGR is also shown as (W_T/W_0)^(12/T) âˆ’ 1.
- Portfolio return: Î¼_p = wáµ€Î¼
- **Portfolio volatility uses the full covariance matrix:**
  - Monthly sample covariance: Î£_m = Cov(r), a 7Ã—7 matrix with (nâˆ’1) in the denominator.
  - Annualized covariance: **Î£ = 12 Â· Î£_m**
  - **Ïƒ_p = âˆš(wáµ€ Î£ w) = âˆš( Î£_i Î£_j w_i w_j Î£_ij )**, where w is the 7Ã—1 weight vector.
  - Code: `np.sqrt(w @ cov_annual @ w)`.
  - This is *not* Î£ w_i Ïƒ_i. The UI shows the naive weighted-average Ïƒ next to it to illustrate the diversification benefit, and a pytest checks a two-asset case by hand: Ïƒ_pÂ² = wâ‚Â²Ïƒâ‚Â² + wâ‚‚Â²Ïƒâ‚‚Â² + 2wâ‚wâ‚‚ÏÏƒâ‚Ïƒâ‚‚.
- Sharpe ratio: (Î¼_p âˆ’ r_f) / Ïƒ_p, where r_f = mean(DTB3 over the lookback)/100. The current DTB3 value is displayed too.
- Backtest: W_t = 10,000 Â· Î (1 + wáµ€r_s), rebalanced monthly.
- Max drawdown: min_t (W_t / max_{sâ‰¤t} W_s âˆ’ 1)
- Monte Carlo: 5,000 paths with monthly portfolio returns drawn from N(wáµ€Î¼Ìƒ/12, wáµ€Î£w/12). Î¼Ìƒ equals Î¼ except that the cash ETF (BIL) uses the **current** DTB3, because the forward-looking cash return is known today. Î£ stays historical. Start value $10,000 (editable), optional monthly contribution (default $0), fixed seed for reproducibility, 10/50/90 percentile bands over the user's horizon (changed from 5/25/50/75/95 at the user's request in M6).
- **Trade-offs:**
  - Monthly data is less noisy than daily and avoids the autocorrelation problems of daily data in bonds, but gives fewer observations.
  - A 10-year window excludes 2008 and is dominated by a bull market, so it probably overstates equity Î¼.
  - Arithmetic Î¼ is greater than or equal to the geometric return.
  - The normal assumption understates fat tails.
  - All of these are listed in the Limitations section.
- **Limitations text (in the app and README):** the 10-year window overweights an unusually strong decade for US equities and includes the 2022 bond drawdown. Expected returns are therefore illustrative, not forecasts.
- **Risk-free rate usage:** the Sharpe ratio uses the *average* DTB3 over the lookback, matching the historical returns. The Monte Carlo cash return uses the *current* DTB3.

## File structure
```
fin471-robo-advisor/
â”œâ”€â”€ app.py              # Streamlit UI only
â”œâ”€â”€ finance.py          # pure math, no I/O
â”œâ”€â”€ profiles.py         # questions, scoring, base allocations, horizon tilt
â”œâ”€â”€ data.py             # yfinance/Tiingo/snapshot prices, FRED, Finnhub; st.cache_data
â”œâ”€â”€ scripts/check_apis.py   # live smoke test of every key/endpoint
â”œâ”€â”€ scripts/build_snapshot.py  # regenerates data/snapshot_prices.csv
â”œâ”€â”€ data/snapshot_prices.csv  # bundled monthly fallback (generated in M3)
â”œâ”€â”€ tests/test_finance.py, tests/test_profiles.py
â”œâ”€â”€ docs/PLAN.md, docs/AI_USAGE.md
â”œâ”€â”€ screenshots/        # placeholders + README references
â”œâ”€â”€ requirements.txt, .env.example, .gitignore, README.md
```
**Libraries:** streamlit, pandas, numpy, plotly, yfinance, requests, python-dotenv, pytest (pinned versions).

**Error-handling design:**
- Each `data.py` function returns `(data, status)`, where status is `live`, `cache`, `snapshot` or `error` plus a message.
- All calls use requests with a timeout. 401/403 means a bad key, 429 means rate-limited, and timeouts are reported clearly.
- Missing keys produce a sidebar warning, and the app still runs on the snapshot.
- The sidebar shows a data-source badge.
- Weights that don't sum to 100 produce a validation message and an optional normalize button.
- Cache lifetimes (`st.cache_data` ttl): prices 24h, FRED 24h, quotes 5 min.

## Milestones (each one is testable on its own; AI_USAGE.md is updated after each)
- **M0 Scaffold:** `git init`, .gitignore (.env, caches), .env.example, requirements.txt, docs/PLAN.md (this plan), docs/AI_USAGE.md (log starts with this session). *Test:* `pip install -r requirements.txt`.
- **M1 finance.py and tests:** hand-checkable cases, e.g. two assets with known Ïƒ and Ï giving Ïƒ_p by hand, a 2-period return giving CAGR, the price path 100â†’120â†’90â†’110 giving MDD of âˆ’25%, and a Sharpe ratio from simple numbers. **Required volatility test:** two assets with annual vol 20% and 10%, Ï = 0, weights 50/50. Î£ = [[0.04, 0], [0, 0.01]], so Ïƒ_p = âˆš(0.5Â²Â·0.04 + 0.5Â²Â·0.01) = âˆš0.0125 â‰ˆ **0.1118**. The test asserts â‰ˆ0.1118 and explicitly asserts it is â‰  0.15, the naive weighted average. *Test:* `pytest`. **Checkpoint:** stop after M1 and show the user the volatility function and the pytest output before starting M2.
- **M2 profiles.py and tests:** score bounds, cut-offs, caps, weights summing to 1, and the 25-year-old vs 60-year-old difference. *Test:* `pytest`.
- **M3 data.py and check_apis.py:** fallback chain and the snapshot CSV. *Test:* `python scripts/check_apis.py` with keys, then with a deliberately bad key.
- **M4 App v1:** sidebar questionnaire, score explanation, recommended allocation table and donut chart.
- **M5 Stats:** per-ETF table (Î¼, Ïƒ), portfolio Î¼/Ïƒ/Sharpe/MDD, $10k backtest chart, lookback selector.
- **M6 Monte Carlo fan chart** plus a risk/return scatter of the 3 profiles (current portfolio highlighted).
- **M7 Manual override:** editable weights in `st.data_editor`, with stats and charts recomputed live and a reset button.
- **M8 Robustness pass:** run with no .env, bad keys and no network (snapshot), check invalid inputs, and confirm nothing crashes.
- **M9 Content:** Methodology & Assumptions and Limitations expanders, a top-of-page disclaimer, the Finnhub live quote panel, README (all required sections plus Step 0 notes), and screenshot placeholders.

## Remaining risks and open items
- **Snapshot CSV (approved):** commit `data/snapshot_prices.csv`, labeled "educational sample" in its header comment, in the README and in the UI badge. Also commit `scripts/build_snapshot.py`, which regenerates it from yfinance.
- **yfinance breakage:** Yahoo changes can break it at any time. The fallbacks cover this, but your demo should be rehearsed with a warm cache.
- **Finnhub `/quote` for ETFs:** expected to work for US ETFs. M3 confirms it live, and if any ticker returns zeros the UI will show "quote unavailable".
- **Not personalized advice:** the disclaimer appears at the top, in Methodology, and in the README. No taxes, fees or account types are modeled.

## Verification
- `pytest` passes, including the hand-checked math and the 25 vs 60 scenario.
- `python scripts/check_apis.py` reports the status of each API.
- `streamlit run app.py`: change the sliders and questions, then confirm the profile, allocation, stats and all 4 charts update. Override weights, then check the stats change.
- Rename .env or disconnect from the network: the app shows clear messages, runs on the snapshot and never shows a traceback.
- Fresh-clone test: in a new folder, follow the README steps exactly.
