"""Inkling UI. Run from the repo root: python -m streamlit run app/streamlit_app.py

Every view shows a source, a limit and a next action (slides-08 p.53). Data comes through the
contracts, so real layers can replace the stubs without touching this file. What's still mocked
is labeled on screen.
"""

import sys
from pathlib import Path

# Streamlit Cloud runs `streamlit run app/streamlit_app.py`, which doesn't put the repo root on
# the import path. Add it so `agent`, `contracts` and `signals` import the same way everywhere.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from agent.stub import respond  # noqa: E402
from app.cycle_clock import cycle_clock_svg, nights_svg  # noqa: E402
from app.summary import LIMIT, coverage_line, long_date, short_date, today_summary  # noqa: E402
from contracts import AgentResponse, CheckIn, DailyRecord, Escalation, PhaseEstimate  # noqa: E402
from signals.stub import estimate_phase, get_daily_records  # noqa: E402

USER_ID = "synthetic-maya"
VIEWS = ["Today", "Check-in", "Ask"]
DEMO_STATES = [
    "Normal",
    "Too few nights",
    "Fitbit sync failed",
    "Live answer unavailable",
    "Red flag",
]
BLEEDING = {
    "None": "none",
    "Spotting": "spot",
    "Light": "light",
    "Medium": "medium",
    "Heavy": "heavy",
}
PAIN = {"None": 0, "Mild": 3, "Moderate": 6, "Severe": 9}  # pain scale still open, see D25
SYMPTOMS = ["Bloating", "Cramps", "Headache", "Tender breasts", "Trouble sleeping"]
SUGGESTED = ["Is a late period normal for me?", "Why do I feel so tired this week?"]
CSS = """
<style>
.block-container {max-width: 960px; padding-top: 3rem;}
.stButton button, .stFormSubmitButton button {min-height: 44px;}
@media (max-width: 640px) {
  .block-container {padding-top: 1rem;}
  h1 {font-size: 1.8rem !important; padding: 0 !important;}
}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
  color: #4e4558 !important; opacity: 1 !important;
}
.badge {background: #fdf1dc; border: 1px solid #e9cf9c; border-radius: 999px; color: #6b4a00;
  display: inline-block; font-size: .8rem; font-weight: 600; padding: .2rem .7rem;}
</style>
"""


def go_to(view: str) -> None:
    st.session_state.view = view


def on_demo_change() -> None:
    if st.session_state.demo == "Red flag":
        st.session_state.view = "Ask"


def reset_demo() -> None:
    st.session_state.demo = "Normal"


def load_data(demo: str) -> tuple[PhaseEstimate, list[DailyRecord]]:
    est = estimate_phase(USER_ID)
    records = get_daily_records(USER_ID)
    if demo == "Too few nights":
        records = records[:1]
        est = est.model_copy(
            update={
                "phase": "unknown",
                "ovulation_est_date": None,
                "ovulation_window": None,
                "confidence": 0.1,
                "method": "calendar",
                "signals_used": [],
            }
        )
    elif demo == "Fitbit sync failed":
        records = records[:-1]
    return est, records


def red_flag_response() -> AgentResponse:
    """Preview only. The real trigger is the rule router (D5), which isn't built yet."""
    return AgentResponse(
        mode="summary",
        text="Soaking a pad every hour is something a clinician should look at. "
        "Inkling can’t assess this and won’t try to explain it here.",
        uncertainty_note="Triggered by a safety rule, not the AI.",
        safety="red_flag",
        escalation=Escalation(
            reason="This is worth getting care today.",
            nearby_care="Contact campus health or an urgent care clinic today.",
        ),
    )


def header() -> None:
    left, right = st.columns([3, 1])
    left.title("Inkling")
    right.markdown('<span class="badge">SYNTHETIC DATA</span>', unsafe_allow_html=True)
    st.radio("Go to", VIEWS, key="view", horizontal=True, label_visibility="collapsed")


def demo_control() -> str:
    with st.expander("Demo · preview other states"):
        st.selectbox(
            "State to preview",
            DEMO_STATES,
            key="demo",
            on_change=on_demo_change,
            help="Forces a failure or safety state for testing and the mock demo.",
        )
    return st.session_state.demo


def footer() -> None:
    st.caption("Patterns, not a diagnosis. Inkling isn’t a medical device.")


def today_view(est: PhaseEstimate, records: list[DailyRecord], demo: str) -> None:
    if demo == "Fitbit sync failed":
        st.warning(
            f"Could not reach Fitbit. Showing cached data through {short_date(records[-1].date)}."
        )
        st.button("Retry sync", on_click=reset_demo)
    dial, card = st.columns(2, gap="large")
    dial.markdown(cycle_clock_svg(est, records), unsafe_allow_html=True)
    headline, body = today_summary(est, records)
    with card.container(border=True):
        st.subheader(headline)
        st.write(body)
        st.markdown(f"**{coverage_line(est, records)}**")
        st.caption(LIMIT)
        with st.expander(f"See the last {len(records)} nights"):
            st.markdown("**Skin temp vs. your usual (°C)**")
            st.markdown(nights_svg(records), unsafe_allow_html=True)
            latest = next((r for r in reversed(records) if r.rhr_bpm is not None), None)
            if latest:
                st.caption(f"Resting HR {latest.rhr_bpm:.0f} bpm on {short_date(latest.date)}")
    st.button(
        "Ask about this", type="primary", on_click=go_to, args=("Ask",), use_container_width=True
    )
    st.button(
        f"Check in for {long_date(est.as_of)}",
        on_click=go_to,
        args=("Check-in",),
        use_container_width=True,
    )


def save_checkin(day, checkin: CheckIn) -> None:
    saved = st.session_state.checkins
    st.session_state.last_save = (day, saved.get(day))
    saved[day] = checkin


def undo_checkin() -> None:
    day, previous = st.session_state.pop("last_save")
    if previous is None:
        del st.session_state.checkins[day]
    else:
        st.session_state.checkins[day] = previous


def checkin_view(est: PhaseEstimate) -> None:
    day = est.as_of
    st.subheader(f"Check-in for {long_date(day)}")
    st.caption("About 15 seconds. Skip anything.")
    with st.form("checkin"):
        bleeding = st.radio("Bleeding", list(BLEEDING), index=None, horizontal=True, key="bleeding")
        energy = st.radio("Energy (1 low, 5 high)", [1, 2, 3, 4, 5], index=None, horizontal=True)
        pain = st.radio("Pain", list(PAIN), index=None, horizontal=True, key="pain")
        symptoms = st.multiselect("Anything else?", SYMPTOMS)
        submitted = st.form_submit_button("Save check-in", type="primary")
    if submitted:
        save_checkin(
            day,
            CheckIn(
                energy=energy,
                bleeding=BLEEDING[bleeding] if bleeding else None,
                pain=PAIN[pain] if pain else None,
                symptoms=[s.lower() for s in symptoms],
            ),
        )
    if "last_save" in st.session_state:
        saved_day = st.session_state.last_save[0]
        st.success(f"Check-in saved for {long_date(saved_day)}")
        checkin = st.session_state.checkins[saved_day]
        if checkin.bleeding == "heavy" or (checkin.pain or 0) >= PAIN["Severe"]:
            st.warning(
                "Very heavy bleeding or severe pain is worth asking a clinician about. "
                "If you feel faint or dizzy, call 911 or go to an emergency room."
            )
        undo, done = st.columns(2)
        undo.button("Undo", key="undo", on_click=undo_checkin, use_container_width=True)
        done.button("Done", key="done", on_click=go_to, args=("Today",), use_container_width=True)
    st.caption("Kept for this session only. Nothing is shared. Saving between visits is not built.")


def render_response(r: AgentResponse) -> None:
    if r.fallback_used:
        st.warning("Live answer unavailable. Showing a saved answer, labeled as a fallback.")
    if r.safety == "red_flag":
        st.error(f"**Paused: this needs a person. {r.escalation.reason}**")
        st.write(r.text)
        st.error(
            "If you feel faint, dizzy or short of breath, call 911 or go to an emergency room."
        )
        if r.escalation.nearby_care:
            st.markdown(f"**Next step:** {r.escalation.nearby_care}")
        st.caption(r.uncertainty_note)
        return
    if r.safety == "caution":
        st.warning("Worth asking a clinician about.")
    st.write(r.text)
    for chip in r.data_chips:
        st.markdown(f"**From your data · {chip.label}:** {chip.value} &nbsp; `data: {chip.source}`")
    for ev in r.evidence_chips:
        st.markdown(f"**From trusted sources:** [{ev.source_org}: {ev.title}]({ev.url})")
        with st.expander("See the passage"):
            st.write(ev.snippet)
    st.caption(r.uncertainty_note)


def ask_view(demo: str) -> None:
    if demo == "Red flag":
        st.chat_message("user").write(
            "I’ve been soaking through a pad every hour since this morning"
        )
        render_response(red_flag_response())
        st.caption("Preview of the red-flag state. The rule router isn’t built yet (D5).")
        st.button("Back to chat", on_click=reset_demo)
        return

    st.info("Prototype: answers come from a stub agent. No LLM yet, and no red-flag rules yet.")
    mode = st.radio(
        "What are you asking about?",
        ["General question", "My own data"],
        horizontal=True,
    )
    for prompt in SUGGESTED:
        if st.button(prompt):
            st.session_state.pending = prompt
    typed = st.chat_input("Ask about your cycle…")
    question = typed or st.session_state.pop("pending", None)
    if question:
        with st.spinner("Checking sources…"):
            r = respond(question, mode="education" if mode == "General question" else "summary")
        if demo == "Live answer unavailable":
            r = r.model_copy(update={"fallback_used": True})
        st.session_state.chat.append((question, r))
    for asked, r in reversed(st.session_state.chat):
        st.chat_message("user").write(asked)
        with st.chat_message("assistant"):
            render_response(r)


st.set_page_config(page_title="Inkling", page_icon="🌙", layout="centered")
st.markdown(CSS, unsafe_allow_html=True)
for key, default in (("view", "Today"), ("demo", "Normal"), ("checkins", {}), ("chat", [])):
    st.session_state.setdefault(key, default)

header()
demo = demo_control()
estimate, nights = load_data(demo)
if st.session_state.view == "Today":
    today_view(estimate, nights, demo)
elif st.session_state.view == "Check-in":
    checkin_view(estimate)
else:
    ask_view(demo)
footer()
