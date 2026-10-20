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
