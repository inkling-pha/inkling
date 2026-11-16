from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app.cycle_clock import cycle_clock_svg, nights_svg
from app.summary import coverage_line, today_summary, warm_streak
from signals.stub import estimate_phase, get_daily_records

BANNED = ("you have pcos", "you are ovulating", "you are pregnant", "% confident")


def app() -> AppTest:
    return AppTest.from_file("../app/streamlit_app.py", default_timeout=10).run()


def texts(at: AppTest) -> str:
    blocks = (at.markdown, at.caption, at.subheader, at.info, at.warning, at.error, at.success)
    return "\n".join(element.value for block in blocks for element in block)


def go(at: AppTest, view: str) -> AppTest:
    return at.radio(key="view").set_value(view).run()


def test_today_shows_source_coverage_limit_and_next_action():
    at = app()
    assert not at.exception
    page = texts(at)
    assert "Synthetic Fitbit data · 2 of 3 nights recorded, Oct 20–Oct 22" in page
    assert "Not for birth control" in page
    assert "Ask about this" in [b.label for b in at.button]


def test_today_never_shows_a_numeric_confidence_or_diagnosis():
    page = texts(app()).lower()
    assert "0.55" not in page
    assert not any(phrase in page for phrase in BANNED)


def test_next_action_opens_ask():
    at = app()
    next(b for b in at.button if b.label == "Ask about this").click().run()
    assert at.session_state["view"] == "Ask"


def test_checkin_saves_then_undo_removes_it():
    at = go(app(), "Check-in")
    at.radio(key="bleeding").set_value("Light")
    at.button(key="FormSubmitter:checkin-Save check-in").click().run()
    assert not at.exception
    assert any("Check-in saved for Thu Oct 22" in s.value for s in at.success)
    assert at.session_state["checkins"][date(2026, 10, 22)].bleeding == "light"
    at.button(key="undo").click().run()
    assert date(2026, 10, 22) not in at.session_state["checkins"]


def test_severe_checkin_points_to_a_clinician():
    at = go(app(), "Check-in")
    at.radio(key="pain").set_value("Severe")
    at.button(key="FormSubmitter:checkin-Save check-in").click().run()
    assert any("clinician" in w.value for w in at.warning)


def test_ask_labels_the_mocked_agent_and_shows_the_source():
    at = go(app(), "Ask")
    at.chat_input[0].set_value("Why do I feel so tired?").run()
    assert not at.exception
    page = texts(at)
    assert "No LLM yet" in page
    assert "MedlinePlus" in page


def test_red_flag_pauses_the_conversation():
    at = app()
    at.selectbox(key="demo").set_value("Red flag").run()
    assert at.session_state["view"] == "Ask"
    assert any("911" in e.value for e in at.error)
    assert len(at.chat_input) == 0


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("Too few nights", "Not enough data yet"),
        ("Fitbit sync failed", "Could not reach Fitbit"),
    ],
)
def test_failure_states_are_visible(state, expected):
    at = app()
    at.selectbox(key="demo").set_value(state).run()
    assert not at.exception
    assert expected in texts(at)


def test_live_answer_fallback_is_labeled():
    at = app()
    at.selectbox(key="demo").set_value("Live answer unavailable").run()
    go(at, "Ask").chat_input[0].set_value("What is a luteal phase?").run()
    assert any("saved answer" in w.value for w in at.warning)


def test_summary_needs_two_warm_nights_to_call_it_a_pattern():
    records = get_daily_records("synthetic-maya")
    assert warm_streak(records) == 1
    assert today_summary(estimate_phase("synthetic-maya"), records)[0] == "Too early to tell"


def test_coverage_counts_missing_nights():
    est = estimate_phase("synthetic-maya")
    assert "2 of 3" in coverage_line(est, get_daily_records("synthetic-maya"))
    assert "no nights" in coverage_line(est, [])


def test_svgs_have_text_alternatives_and_mark_missing_nights():
    records = get_daily_records("synthetic-maya")
    assert "Likely window: Oct 17–21" in cycle_clock_svg(estimate_phase("synthetic-maya"), records)
    assert "no data" in nights_svg(records)
