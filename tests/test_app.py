"""Smoke tests that run the real Streamlit script headlessly (streamlit.testing.AppTest)."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run_app(age=None, horizon=None):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    if age is not None:
        at.number_input(key="age").set_value(age).run()
    if horizon is not None:
        at.slider(key="horizon").set_value(horizon).run()
    assert not at.exception, at.exception
    return at


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def test_app_runs_without_errors_and_shows_disclaimer():
    at = run_app()
    assert not at.exception
    assert any("not investment advice" in i.value for i in at.info)


def test_age_change_resets_horizon_and_changes_recommendation():
    young = run_app(age=25)
    assert young.slider(key="horizon").value == 40
    assert metric(young, "Your profile") == "Moderate"
    assert metric(young, "Growth / defensive") == "70% / 30%"

    older = run_app(age=60)
    assert older.slider(key="horizon").value == 5
    assert metric(older, "Your profile") == "Conservative"
    assert metric(older, "Growth / defensive") == "25% / 75%"


def test_short_horizon_cap_is_explained():
    at = run_app(horizon=2)
    for q in ("drop_reaction", "goal", "experience", "stability", "tradeoff"):
        at.radio(key=f"q_{q}").set_value(4)
    at.run()
    assert not at.exception
    assert metric(at, "Your profile") == "Conservative"
    assert any("under 3 years" in m.value for m in at.markdown)
