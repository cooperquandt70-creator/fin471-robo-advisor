# AI Coding Agent Usage Log

Running log of what I (the student) asked the AI coding agent (Claude Code, model Claude Opus 5.5) to do and what it changed. This feeds the README's "How the AI coding agent was used" section.

---

## Session 1 — 2026-10-20

### 1. Planning request (no code)
**I asked:** Plan the whole project before writing code. First verify (Step 0), using current docs, which free API endpoints work: Finnhub ETF endpoints and candles, a free historical price source, and FRED for the risk-free rate. Then propose the ETF universe, allocations, scoring, formulas, file structure, milestones and open questions.

**Agent did:**
- Read Finnhub's official `swagger.json`. Confirmed that `/stock/candle`, `/etf/profile`, `/etf/holdings`, `/etf/sector`, `/etf/country` and `/etf/allocation` are all premium. Free endpoints include `/quote`, `/search`, `/stock/metric` and `/company-news`.
- Checked the PyPI page for yfinance (v1.7.0, unofficial, rate-limit issues), the Tiingo pricing page (free: 50 req/hr, 1,000/day, 500 symbols/mo, internal use only), the Alpha Vantage docs (25 req/day; daily adjusted and full output are premium) and the FRED observations endpoint docs.
- Asked me four clarifying questions. **My decisions:** yfinance primary with Tiingo and a bundled-snapshot fallback; 10-year monthly lookback; Sharpe uses the average DTB3 over the lookback; Finnhub is used for a live quote panel.

### 2. Plan revisions I requested before approving
**I asked:**
1. Show the exact covariance-matrix volatility formula.
2. Add to Limitations that the 10-year window overweights a strong US equity decade and includes the 2022 bond drawdown.
3. Explain why horizon is in both the score and the tilt.
4. Use the average DTB3 for Sharpe and the current DTB3 for the Monte Carlo cash return.
5. Commit the sample CSV labeled "educational sample", plus a script to regenerate it.
6. Add a required pytest: 20% and 10% vol, ρ = 0, 50/50 weights → σ_p ≈ 0.1118, not 0.15.

**Agent did:** updated the plan with all of these. I approved it, and it was saved to `docs/PLAN.md`.

### 3. Milestone 0 — scaffold
**Agent did:**
- Created `.gitignore` (excludes `.env`, `.venv`, caches) and `.env.example` (Finnhub, FRED and Tiingo keys, with signup links).
- Created a `.venv`, installed the packages and pinned the exact resolved versions in `requirements.txt`.
- Created the folders `docs/`, `tests/`, `scripts/`, `data/` and `screenshots/`.
- `git init` was **skipped** at first because Git was not installed on this machine.

**Follow-up (after I installed Git):**
- **I asked:** init the repo, confirm `.env` and `.venv` are ignored, and commit M0 and M1 separately. From now on, commit after each milestone.
- **Agent did:**
  - Ran `git init` with a repo-local author identity.
  - Verified with `git check-ignore` that `.env` and `.venv/` are ignored.
  - Also ignored `.claude/settings.local.json`, which holds personal tool permissions.
  - Made two commits: the M0 scaffold, then M1 finance + tests.

### 4. Milestone 1 — `finance.py` + tests
**Agent did:**
- Wrote `finance.py`, which is pure functions only:
  - monthly returns
  - annualized return, volatility and covariance (×12)
  - portfolio return wᵀμ
  - **portfolio volatility √(wᵀΣw)**
  - naive weighted volatility (for comparison)
  - Sharpe ratio
  - monthly-rebalanced growth of $10,000
  - CAGR and max drawdown
  - seeded Monte Carlo paths and percentile bands
- Wrote `tests/test_finance.py`: 17 hand-checkable tests, including the required 0.1118 vs 0.15 case, a ρ = 0.5 case, a ρ = 1 case, the MDD path 100→120→90→110 = −25%, a Sharpe of 0.5, and a deterministic Monte Carlo check (1.01¹²).
- **Result:** `pytest`: 17 passed.

### 5. Milestone 2 — `profiles.py` + tests
**I asked:** start M2, and commit after each milestone from now on.

**Agent did:**
- Wrote `profiles.py`, containing:
  - the 7-ETF universe and growth/defensive sleeves
  - the base allocation table
  - five risk questions scored 0–4
  - horizon points (0–10)
  - profile cut-offs (0–12 / 13–21 / 22–30)
  - safety caps (horizon < 3 yrs → Conservative; 3–5 yrs → at most Moderate)
  - a plain-English `explain()`
  - the horizon tilt (±10 pp, proportional within each sleeve, growth kept at 20–95%)
  - `recommend()`, which ties these together
- Wrote `tests/test_profiles.py`, covering:
  - horizon-point boundaries, score bounds and cut-offs
  - both caps
  - weights summing to 1 for every profile × horizon 1–40
  - within-sleeve mix preserved under the tilt
  - tilt ranges never overlapping between profiles
  - invalid inputs raising `ValueError`
  - **the required example:** a 25-year-old (middle answers) scores 20 → Moderate with a 70% growth share; a 60-year-old scores 12 → Conservative with a 25% growth share.
- **Result:** `pytest`: 176 passed.

### 6. Milestone 3 — `data.py`, API check, snapshot
**I asked:** go (after I added my free keys to `.env`).

**Agent did:**
- Wrote `data.py`:
  - **Price chain:** yfinance → Tiingo → last good local copy (`data/cache/`, git-ignored) → bundled educational sample.
  - **Risk-free rate:** FRED DTB3, as monthly averages → local copy → sample.
  - **Quotes:** Finnhub `/quote`.
  - **Error handling:** every function returns a `DataResult(data, source, message)` instead of crashing. HTTP 401/403/429, timeouts, network errors and bad JSON become friendly messages that never contain an API key. Finnhub and Tiingo keys are sent in headers, not URLs.
  - **Caching:** `st.cache_data` wrappers (24h for prices and FRED, 5 min for quotes).
- Wrote `scripts/check_apis.py`, which reports OK/FAIL per API without printing keys. Its `--bad-key` mode tests error handling.
- Wrote `scripts/build_snapshot.py`, which generates `data/snapshot_prices.csv` and `data/snapshot_dtb3.csv` with an "EDUCATIONAL SAMPLE" header.
- **Live results with my keys (2026-10-20):**
  - Finnhub `/quote` VTI: OK.
  - Finnhub `/etf/profile` and `/stock/candle`: HTTP 403, which confirms the Step 0 finding that both are premium-only.
  - FRED DTB3: OK (latest Sep 2026 = 3.94%).
  - yfinance: OK (7 ETFs, Jan 2013–Sep 2026).
  - Tiingo: OK.
  - yfinance vs Tiingo 10-year monthly returns agree within 0.03% (VTI) and 0.23% (BND).
- **Bad-key run:** every keyed API failed with a clear message and no crash.
- Wrote `tests/test_data.py` (offline, mocked): fallback order, an all-sources-down result, HTTP error mapping, key-leak checks, missing keys, and dropping the incomplete current month.
- **Result:** `pytest`: 192 passed.
- **Security catch:** the agent noticed an untracked `.env.txt` holding my real keys, which was not covered by `.gitignore`. It added an `.env.*` ignore rule (still allowing `.env.example`) and confirmed via `git log` that no key file was ever committed. It recommended that I delete `.env.txt`.

### 7. Milestone 4 — App v1 (questionnaire, profile, allocation)
**I asked:** go for milestone 4.

**Agent did:**
- Wrote `app.py` (UI only):
  - **Disclaimer:** an "educational illustration, not advice" banner at the top.
  - **Sidebar inputs:** age (changing it resets the horizon slider to 65 − age), a horizon slider, and five risk questions as radio buttons.
  - **Profile metrics:** profile, score out of 30, and the growth/defensive split.
  - **Explanation:** a "Why you landed here" sentence and an expandable score breakdown listing the scoring rules.
  - **Allocation:** a table (your weight vs base weight), a sentence explaining the horizon tilt, and a Plotly donut with one fixed colour per ETF.
- Wrote `tests/test_app.py`, which uses Streamlit's `AppTest` to run the real script headlessly. It checks:
  - no exceptions and the disclaimer is visible
  - age 25 → horizon 40, Moderate, 70%/30%
  - age 60 → horizon 5, Conservative, 25%/75%
  - the short-horizon cap is explained on screen
- **Bug the tests caught:** the first version crashed because Plotly 7 rejects `hover_data` as a dict when `color` is also set. Fixed by switching to `custom_data`.
- **Checked in the browser:**
  - Changing age to 60 updated everything live.
  - At narrow widths the weight columns were cut off, so the weights were moved next to the ticker and formatted to one decimal place.
- Added `.streamlit/config.toml` to turn off Streamlit's usage statistics.
- **Result:** `pytest`: 195 passed.

### 8. Pre-M5 fixes: horizon label, ages 65+, launch.json
**I asked:**
1. Relabel the horizon input to "Years until you start withdrawing money", and add a Limitations note that retirement spending extends the real horizon.
2. Check ages 64, 65, 66 and 80: the horizon must never be 0 or negative, and the app must not error.
3. Explain what `launch.json` is.

**Agent did:**
- Relabelled the slider and updated its help text.
- Added a `LIMITATIONS` list and a Limitations expander to the app, with the retirement-spending note and the 10-year-lookback note.
- Checked those ages: `default_horizon()` already floors at 1 year, so they all get 1 year → Conservative (21% growth). Documented the floor in the docstring.
- Added tests: `test_profiles.py` (ages 64/65/66/80/90 → horizon 1, valid recommendation) and `test_app.py` (the same ages through the real UI with no errors, plus the new label and Limitations note).
- **launch.json:** explained that `.claude/launch.json` only tells the Claude desktop app's browser pane how to start Streamlit. It isn't part of the project and stays git-ignored.
- **Result:** `pytest`: 205 passed.
