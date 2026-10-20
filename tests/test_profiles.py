"""Unit tests for profiles.py: scoring, cut-offs, caps, and allocations."""

import pytest

import profiles as pr

MIDDLE = {q["key"]: 2 for q in pr.QUESTIONS}   # "middle of the road" answers = 10 pts
LOWEST = {q["key"]: 0 for q in pr.QUESTIONS}
HIGHEST = {q["key"]: 4 for q in pr.QUESTIONS}


# --- Questionnaire structure -----------------------------------------------
def test_five_questions_each_scored_0_to_4():
    assert len(pr.QUESTIONS) == 5
    for q in pr.QUESTIONS:
        assert sorted(p for _, p in q["options"]) == [0, 1, 2, 3, 4]


# --- Horizon points and score bounds ---------------------------------------
@pytest.mark.parametrize(
    "years, points",
    [(1, 0), (2, 0), (3, 2), (5, 2), (6, 5), (10, 5), (11, 8), (20, 8), (21, 10), (40, 10)],
)
def test_horizon_points_boundaries(years, points):
    assert pr.horizon_points(years) == points


def test_default_horizon():
    assert pr.default_horizon(25) == 40
    assert pr.default_horizon(60) == 5
    assert pr.default_horizon(80) == 1   # never below 1 year
    assert pr.default_horizon(18) == 40  # never above 40 years


@pytest.mark.parametrize("age, horizon", [(64, 1), (65, 1), (66, 1), (80, 1), (90, 1)])
def test_horizon_never_zero_or_negative_near_or_past_65(age, horizon):
    h = pr.default_horizon(age)
    assert h == horizon and h >= pr.MIN_HORIZON
    rec = pr.recommend(h, MIDDLE)  # must not raise
    assert rec.score.profile == "Conservative"  # under 3 years forces Conservative
    assert sum(rec.weights.values()) == pytest.approx(1.0)


def test_score_bounds():
    low = pr.score(1, LOWEST)
    high = pr.score(40, HIGHEST)
    assert (low.total, low.profile) == (0, "Conservative")
    assert (high.total, high.profile) == (30, "Aggressive")


@pytest.mark.parametrize(
    "total, profile",
    [(0, "Conservative"), (12, "Conservative"), (13, "Moderate"), (21, "Moderate"), (22, "Aggressive"), (30, "Aggressive")],
)
def test_profile_cutoffs(total, profile):
    assert pr.profile_from_total(total) == profile


# --- Safety caps -----------------------------------------------------------
def test_short_horizon_forces_conservative():
    r = pr.score(2, HIGHEST)  # 0 + 20 = 20 -> Moderate before the cap
    assert r.uncapped_profile == "Moderate"
    assert r.profile == "Conservative"
    assert r.cap_reason is not None


def test_three_to_five_year_horizon_caps_at_moderate():
    r = pr.score(4, HIGHEST)  # 2 + 20 = 22 -> Aggressive before the cap
    assert r.uncapped_profile == "Aggressive"
    assert r.profile == "Moderate"


def test_no_cap_for_long_horizon():
    r = pr.score(30, HIGHEST)
    assert r.profile == "Aggressive" and r.cap_reason is None


# --- Allocations -----------------------------------------------------------
@pytest.mark.parametrize("profile", pr.PROFILES)
def test_base_allocations_sum_to_one_and_cover_universe(profile):
    base = pr.BASE_ALLOCATIONS[profile]
    assert set(base) == set(pr.TICKERS)
    assert sum(base.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("years, tilt", [(10, 0.0), (40, 0.10), (20, 0.10), (5, -0.05), (1, -0.09)])
def test_horizon_tilt(years, tilt):
    assert pr.horizon_tilt(years) == pytest.approx(tilt)


@pytest.mark.parametrize("profile", pr.PROFILES)
@pytest.mark.parametrize("years", range(1, 41))
def test_tilted_weights_sum_to_one_and_non_negative(profile, years):
    w = pr.apply_tilt(pr.BASE_ALLOCATIONS[profile], pr.horizon_tilt(years))
    assert sum(w.values()) == pytest.approx(1.0)
    assert all(v >= 0 for v in w.values())


def test_tilt_keeps_mix_within_sleeve():
    base = pr.BASE_ALLOCATIONS["Moderate"]
    w = pr.apply_tilt(base, 0.10)
    assert w["VTI"] / w["VXUS"] == pytest.approx(base["VTI"] / base["VXUS"])
    assert w["BND"] / w["TIP"] == pytest.approx(base["BND"] / base["TIP"])
    assert pr.growth_share(w) == pytest.approx(0.70)


def test_tilt_never_moves_a_profile_into_another_profiles_range():
    def growth_range(profile):
        base = pr.BASE_ALLOCATIONS[profile]
        return (pr.growth_share(pr.apply_tilt(base, -pr.MAX_TILT)),
                pr.growth_share(pr.apply_tilt(base, pr.MAX_TILT)))

    cons, mod, aggr = (growth_range(p) for p in pr.PROFILES)
    assert cons[1] < mod[0]
    assert mod[1] < aggr[0]


# --- The required example: 25-year-old vs 60-year-old ---------------------
def test_young_vs_near_retirement_get_meaningfully_different_allocations():
    young = pr.recommend(pr.default_horizon(25), MIDDLE)   # 40 yrs: 10 + 10 = 20
    older = pr.recommend(pr.default_horizon(60), MIDDLE)   # 5 yrs:   2 + 10 = 12

    assert young.score.total == 20 and young.score.profile == "Moderate"
    assert older.score.total == 12 and older.score.profile == "Conservative"
    assert pr.growth_share(young.weights) == pytest.approx(0.70)  # 60% + 10 pp tilt
    assert pr.growth_share(older.weights) == pytest.approx(0.25)  # 30% - 5 pp tilt
    assert pr.growth_share(young.weights) - pr.growth_share(older.weights) >= 0.40


# --- Invalid input ---------------------------------------------------------
@pytest.mark.parametrize("years", [0, 41, -5])
def test_invalid_horizon_raises(years):
    with pytest.raises(ValueError):
        pr.score(years, MIDDLE)


def test_out_of_range_answer_raises():
    with pytest.raises(ValueError):
        pr.score(10, {**MIDDLE, "goal": 5})


def test_missing_answer_raises():
    answers = dict(MIDDLE)
    answers.pop("goal")
    with pytest.raises(ValueError):
        pr.score(10, answers)


def test_explanation_mentions_score_and_cap():
    text = pr.explain(pr.score(2, HIGHEST))
    assert "20 out of 30" in text and "Conservative" in text
