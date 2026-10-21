"""
profiles.py - risk questionnaire, scoring, and ETF allocations.

How a recommendation is built (all rules are transparent and shown in the app):
  1. SCORE  = horizon points (0-10) + five risk-tolerance answers (0-4 each, 0-20)
              -> total 0-30.
  2. PROFILE from the total: 0-12 Conservative, 13-21 Moderate, 22-30 Aggressive.
     Safety caps: horizon < 3 yrs forces Conservative; 3-5 yrs caps at Moderate.
  3. BASE ALLOCATION for that profile (table below).
  4. HORIZON TILT: shift up to +/-10 percentage points between the growth and
     defensive sleeves, so horizon also fine-tunes the mix *within* a profile.

Why horizon is used twice: the score sets the coarse bucket (profile), the tilt
adjusts continuously inside it. The +/-10 pp cap means a tilt can never push a
portfolio into another profile's range.
"""

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# ETF universe
# ---------------------------------------------------------------------------
TICKERS = ["VTI", "VXUS", "VNQ", "BND", "BNDX", "TIP", "BIL"]

ETF_INFO = {
    "VTI": ("Vanguard Total Stock Market ETF", "US stocks"),
    "VXUS": ("Vanguard Total International Stock ETF", "International stocks"),
    "VNQ": ("Vanguard Real Estate ETF", "US REITs"),
    "BND": ("Vanguard Total Bond Market ETF", "US bonds"),
    "BNDX": ("Vanguard Total International Bond ETF (USD-hedged)", "International bonds"),
    "TIP": ("iShares TIPS Bond ETF", "US inflation-protected bonds"),
    "BIL": ("SPDR Bloomberg 1-3 Month T-Bill ETF", "Cash-like (T-bills)"),
}

GROWTH = ["VTI", "VXUS", "VNQ"]          # stocks + real estate
DEFENSIVE = ["BND", "BNDX", "TIP", "BIL"]  # bonds + cash
CASH_TICKER = "BIL"

PROFILES = ["Conservative", "Moderate", "Aggressive"]  # ordered least -> most risky

# Asset type, used by the optional "Conservative adjustment" to return assumptions.
ASSET_TYPE = {"VTI": "equity", "VXUS": "equity", "VNQ": "equity",
              "BND": "bond", "BNDX": "bond", "TIP": "bond", "BIL": "cash"}

# "Conservative adjustment": subtract these from historical annual expected returns,
# because the lookback decade was unusually strong for stocks. Cash is unchanged
# (its forward return already comes from today's T-bill rate).
CONSERVATIVE_ADJUSTMENT = {"equity": -0.020, "bond": -0.005, "cash": 0.0}

# Base weights (fractions). Each row sums to 1.
BASE_ALLOCATIONS = {
    "Conservative": {"VTI": 0.18, "VXUS": 0.08, "VNQ": 0.04, "BND": 0.35, "BNDX": 0.10, "TIP": 0.15, "BIL": 0.10},
    "Moderate":     {"VTI": 0.36, "VXUS": 0.18, "VNQ": 0.06, "BND": 0.22, "BNDX": 0.08, "TIP": 0.06, "BIL": 0.04},
    "Aggressive":   {"VTI": 0.50, "VXUS": 0.27, "VNQ": 0.08, "BND": 0.10, "BNDX": 0.03, "TIP": 0.02, "BIL": 0.00},
}

# ---------------------------------------------------------------------------
# Questionnaire
# ---------------------------------------------------------------------------
# Each option is (label, points). Points run 0 (most cautious) to 4 (most risk-tolerant).
QUESTIONS = [
    {
        "key": "drop_reaction",
        "text": "Your portfolio falls 20% in a few months. What do you do?",
        "options": [
            ("Sell everything to stop the losses", 0),
            ("Sell some to reduce risk", 1),
            ("Hold and wait", 2),
            ("Hold and rebalance back to my plan", 3),
            ("Buy more while prices are low", 4),
        ],
    },
    {
        "key": "goal",
        "text": "What is your main goal for this money?",
        "options": [
            ("Preserve what I have", 0),
            ("Generate steady income", 1),
            ("Balance growth and stability", 2),
            ("Grow it over time", 3),
            ("Maximize growth", 4),
        ],
    },
    {
        "key": "experience",
        "text": "How much investing experience do you have?",
        "options": [
            ("None", 0),
            ("Savings accounts / CDs only", 1),
            ("Some mutual funds or ETFs", 2),
            ("Regularly invest in stocks and funds", 3),
            ("Extensive, through several market cycles", 4),
        ],
    },
    {
        "key": "stability",
        "text": "How stable is your income, and do you have an emergency fund?",
        "options": [
            ("Unstable income, no emergency fund", 0),
            ("Unstable income, small emergency fund", 1),
            ("Fairly stable income, some savings", 2),
            ("Stable income, 3-6 months of savings", 3),
            ("Very stable income, 6+ months of savings", 4),
        ],
    },
    {
        "key": "tradeoff",
        "text": "Which one-year range of outcomes on $10,000 would you choose?",
        "options": [
            ("$9,900 to $10,400", 0),
            ("$9,500 to $10,800", 1),
            ("$9,000 to $11,500", 2),
            ("$8,000 to $12,500", 3),
            ("$7,000 to $14,000", 4),
        ],
    },
]

MIN_HORIZON, MAX_HORIZON = 1, 40
RETIREMENT_AGE = 65
MAX_TILT = 0.10                       # +/-10 percentage points
GROWTH_FLOOR, GROWTH_CEILING = 0.20, 0.95


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def default_horizon(age: int) -> int:
    """Default horizon = years until age 65 (when withdrawals start), kept within 1-40 years.

    At 65 or older this would be 0 or negative, so it is floored at 1 year.
    (Spending in retirement actually continues for years; see Limitations in the app.)
    """
    return int(min(max(RETIREMENT_AGE - age, MIN_HORIZON), MAX_HORIZON))


def horizon_points(years: float) -> int:
    """Points for investment horizon: <3 yrs 0, 3-5 2, 6-10 5, 11-20 8, >20 10."""
    if years < 3:
        return 0
    if years <= 5:
        return 2
    if years <= 10:
        return 5
    if years <= 20:
        return 8
    return 10


def profile_from_total(total: int) -> str:
    """Map the 0-30 total score to a profile."""
    if total <= 12:
        return "Conservative"
    if total <= 21:
        return "Moderate"
    return "Aggressive"


@dataclass
class ScoreResult:
    horizon_years: float
    horizon_points: int
    risk_points: int
    total: int
    uncapped_profile: str
    profile: str
    cap_reason: str | None
    breakdown: list = field(default_factory=list)  # (item, points, max points)


def score(horizon_years: float, answers: dict) -> ScoreResult:
    """Score the questionnaire and apply the horizon safety caps.

    `answers` maps each question key to its points (0-4).
    Raises ValueError on invalid input (the app shows the message instead of crashing).
    """
    if not (MIN_HORIZON <= horizon_years <= MAX_HORIZON):
        raise ValueError(f"Horizon must be between {MIN_HORIZON} and {MAX_HORIZON} years.")

    h_pts = horizon_points(horizon_years)
    breakdown = [(f"Investment horizon ({horizon_years:g} years)", h_pts, 10)]
    risk_pts = 0
    for q in QUESTIONS:
        if q["key"] not in answers:
            raise ValueError(f"Missing answer for: {q['text']}")
        pts = answers[q["key"]]
        if pts not in range(0, 5):
            raise ValueError(f"Answer for '{q['key']}' must score 0-4, got {pts!r}.")
        risk_pts += pts
        breakdown.append((q["text"], pts, 4))

    total = h_pts + risk_pts
    uncapped = profile_from_total(total)
    profile, cap_reason = uncapped, None
    if horizon_years < 3 and uncapped != "Conservative":
        profile = "Conservative"
        cap_reason = "A horizon under 3 years leaves little time to recover from a loss, so the profile is limited to Conservative."
    elif horizon_years <= 5 and uncapped == "Aggressive":
        profile = "Moderate"
        cap_reason = "A horizon of 3-5 years caps the profile at Moderate."

    return ScoreResult(horizon_years, h_pts, risk_pts, total, uncapped, profile, cap_reason, breakdown)


def explain(result: ScoreResult) -> str:
    """Plain-English explanation of why the user landed in their profile."""
    text = (
        f"You scored {result.total} out of 30: {result.horizon_points}/10 for your "
        f"{result.horizon_years:g}-year horizon and {result.risk_points}/20 on the risk questions. "
        f"Scores of 0-12 are Conservative, 13-21 Moderate and 22-30 Aggressive, "
        f"so your score points to {result.uncapped_profile}."
    )
    if result.cap_reason:
        text += f" {result.cap_reason} Your profile is therefore {result.profile}."
    return text


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------
def horizon_tilt(horizon_years: float) -> float:
    """Growth tilt = (horizon - 10 yrs) x 1 pp per year, capped at +/-10 pp."""
    return max(-MAX_TILT, min(MAX_TILT, (horizon_years - 10) * 0.01))


def growth_share(weights: dict) -> float:
    return sum(weights.get(t, 0.0) for t in GROWTH)


def apply_tilt(base: dict, tilt: float) -> dict:
    """Move `tilt` from the defensive sleeve to the growth sleeve (negative = the reverse).

    Each sleeve is rescaled proportionally, so the mix *inside* a sleeve
    (e.g. US vs international stocks) stays the same. The growth share is
    kept between 20% and 95%.
    """
    g = growth_share(base)
    new_g = min(GROWTH_CEILING, max(GROWTH_FLOOR, g + tilt))
    out = {}
    for t, w in base.items():
        if t in GROWTH:
            out[t] = w * new_g / g if g > 0 else new_g / len(GROWTH)
        else:
            out[t] = w * (1 - new_g) / (1 - g) if g < 1 else (1 - new_g) / len(DEFENSIVE)
    return out


def return_adjustments(conservative: bool) -> dict:
    """Per-ticker change to annual expected return (decimals). All zero for 'Historical'."""
    return {t: (CONSERVATIVE_ADJUSTMENT[ASSET_TYPE[t]] if conservative else 0.0) for t in TICKERS}


# ---------------------------------------------------------------------------
# Manual (custom) weights
# ---------------------------------------------------------------------------
SUM_TOLERANCE = 0.05  # percentage points; 99.96%-100.04% counts as 100%


def check_custom_weights(weights_pct: dict) -> tuple[str, str]:
    """Validate weights the user typed, in PERCENT (e.g. 42.0 = 42%).

    Returns (status, message) where status is:
      "ok"           - every weight is >= 0 and they sum to 100%
      "not_100"      - valid, but the total isn't 100% (user must fix or normalize)
      "invalid"      - a missing/negative weight or all zeros (can't be used at all)
    """
    values = {}
    for t in TICKERS:
        v = weights_pct.get(t)
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "invalid", f"Every ETF needs a weight; {t} is empty (use 0 for none)."
        if v != v:  # NaN check
            return "invalid", f"Every ETF needs a weight; {t} is empty (use 0 for none)."
        values[t] = v

    negatives = [f"{t} = {v:.1f}%" for t, v in values.items() if v < 0]
    if negatives:
        return "invalid", ("Negative weights (short selling) aren't allowed: " + ", ".join(negatives) +
                           ". Set them to 0 or more.")
    total = sum(values.values())
    if total <= 0:
        return "invalid", "All weights are zero. Give at least one ETF a positive weight."
    if abs(total - 100) > SUM_TOLERANCE:
        return "not_100", f"Your weights add up to {total:.1f}%, not 100%."
    return "ok", ""


def normalize_weights(weights: dict) -> dict:
    """Scale non-negative weights so they sum to 1 (keeps their relative sizes).

    Example: {A: 30, B: 30} -> {A: 0.5, B: 0.5}.
    """
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Weights must have a positive total to normalize.")
    return {t: w / total for t, w in weights.items()}


@dataclass
class Recommendation:
    score: ScoreResult
    base_weights: dict
    tilt: float
    weights: dict


def recommend(horizon_years: float, answers: dict) -> Recommendation:
    """Full pipeline: score -> profile -> base allocation -> horizon tilt."""
    result = score(horizon_years, answers)
    base = BASE_ALLOCATIONS[result.profile]
    tilt = horizon_tilt(horizon_years)
    return Recommendation(result, dict(base), tilt, apply_tilt(base, tilt))
