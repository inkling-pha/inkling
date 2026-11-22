from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app.cycle_clock import cycle_clock_svg, nights_svg
from app.summary import coverage_line, long_date, short_date, today_summary, warm_streak
from contracts import DailyRecord, PhaseEstimate, load_fixture
from signals.stub import estimate_phase, get_daily_records

BANNED = ("you have pcos", "you are ovulating", "you are pregnant", "% confident")


def fixture_records() -> list[DailyRecord]:
    """The 3-day contract fixture, for tests of display logic that need exact values."""
    return [DailyRecord.model_validate(r) for r in load_fixture("daily_records")]


def fixture_estimate() -> PhaseEstimate:
    return PhaseEstimate.model_validate(load_fixture("phase_estimate"))


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
    maya = get_daily_records("synthetic-maya")
    span = f"{short_date(maya[0].date)}–{short_date(maya[-1].date)}"
    assert "Synthetic Fitbit data · " in page and f"of {len(maya)} nights recorded, {span}" in page
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
    today = date.today()  # Maya's last day is always today
    assert any(f"Check-in saved for {long_date(today)}" in s.value for s in at.success)
    assert at.session_state["checkins"][today].bleeding == "light"
    at.button(key="undo").click().run()
    assert today not in at.session_state["checkins"]


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
    records = fixture_records()
    assert warm_streak(records) == 1
    assert today_summary(fixture_estimate(), records)[0] == "Too early to tell"


def test_coverage_counts_missing_nights():
    est = fixture_estimate()
    assert "2 of 3" in coverage_line(est, fixture_records())
    assert "no nights" in coverage_line(est, [])


def test_svgs_have_text_alternatives_and_mark_missing_nights():
    records = fixture_records()
    assert "Likely window: Oct 17–21" in cycle_clock_svg(fixture_estimate(), records)
    assert "no data" in nights_svg(records)


# --- synthetic Maya in the app -------------------------------------------------------------


def test_maya_today_card_is_driven_by_her_phase():
    est, records = estimate_phase("synthetic-maya"), get_daily_records("synthetic-maya")
    assert est.source == "synthetic" and est.phase == "luteal" and est.cycle_day == 34
    assert est.ovulation_window is None  # calendar estimates carry no fertility timing (D25)
    headline, body = today_summary(est, records)
    assert headline != "Not enough data yet"
    assert "Day 34 · Likely luteal · Low confidence." in body
    assert not any(ch.isdigit() for ch in body.replace("Day 34", ""))  # no dates, no numbers


def test_unknown_phase_still_says_not_enough_data():
    est = fixture_estimate().model_copy(update={"phase": "unknown", "ovulation_window": None})
    assert today_summary(est, fixture_records())[0] == "Not enough data yet"


def test_nights_chart_shows_the_last_week():
    at = app()
    assert any(e.label == "See the last 7 nights" for e in at.expander)


def test_dial_never_puts_today_on_day_one_and_hides_an_empty_legend():
    from app.cycle_clock import DIAL_ROOM_DAYS, _point

    est = estimate_phase("synthetic-maya")
    svg = cycle_clock_svg(est, get_daily_records("synthetic-maya"))
    assert "Likely window</text>" not in svg  # no window drawn, so no legend for one
    x, _ = _point(est.cycle_day, est.cycle_day + DIAL_ROOM_DAYS, 118)
    assert x < 140  # left of the top: not on Day 1
    assert "Likely window</text>" in cycle_clock_svg(fixture_estimate(), fixture_records())
