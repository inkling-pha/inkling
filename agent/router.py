"""Real agent: fertility guard (D25) + red-flag/caution rules (D5) in front of retrieval.

Replaces agent.stub for "education" mode. Rules decide the safety level before anything else
runs — a red flag never reaches retrieval or the LLM path (CLAUDE.md: rules decide first, the
LLM never overrides a rule). "summary" mode still delegates to agent.stub: routing between the
two modes (D7) and what user data may reach an LLM (D14) are still open, so summary stays
data-chips-only until those are decided.

No LLM is wired yet (D8's model name and D14 are open), so an education answer is retrieval plus
a template, not generated prose — `fallback_used` only flags when even retrieval itself fell back
to the canned fixture (e.g. the corpus hasn't been fetched locally: `python -m rag.corpus`).
"""

from typing import Literal

from agent import safety
from agent.fertility_guard import DECLINE_TEXT, is_fertility_timing, strip_fertility_timing
from agent.stub import respond as stub_respond
from contracts import AgentResponse, DataChip, Escalation, Evidence
from rag.retriever import retrieve as live_retrieve
from rag.stub import retrieve as canned_retrieve
from signals.stub import estimate_phase


def _phase_chip(est) -> DataChip:
    return DataChip(
        label="Estimated phase",
        value=f"{est.phase} (day {est.cycle_day})",
        chart_ref=est.chart_ref,
        source=est.source,
    )


def _uncertainty_note(est) -> str:
    window = est.ovulation_window
    if window:
        return f"Ovulation window {window.start} to {window.end}, confidence {est.confidence:.2f}."
    return "Not enough data yet to estimate ovulation."


def _retrieve(question: str, user_context: dict) -> tuple[list[Evidence], bool]:
    try:
        return live_retrieve(question, user_context), False
    except Exception:
        # Corpus not fetched locally, or another retrieval failure (D6's fallback).
        return canned_retrieve(question, user_context), True


def _education_text(question: str, evidence: list[Evidence], fallback_used: bool) -> str:
    if fallback_used:
        return (
            "I couldn't reach the trusted-source index just now, so here's a saved example "
            "instead of a live search."
        )
    if not evidence:
        return "I don't know — nothing in the trusted sources matches this well enough to answer."
    return (
        f"No AI summary yet (D14) — here is what the trusted sources say that's closest to "
        f'"{question}":'
    )


def _red_flag_response(
    mode: Literal["education", "summary"], result: safety.SafetyResult
) -> AgentResponse:
    return AgentResponse(
        mode=mode,
        text=result.reason,
        uncertainty_note="Triggered by a safety rule (D5), not the AI.",
        safety="red_flag",
        escalation=Escalation(
            reason=result.reason,
            nearby_care="Contact campus health or an urgent care clinic today.",
        ),
    )


def _fertility_decline(mode: Literal["education", "summary"], est) -> AgentResponse:
    return AgentResponse(
        mode=mode,
        text=DECLINE_TEXT,
        data_chips=[_phase_chip(est)],
        uncertainty_note="Out of scope: no fertility-timing advice (D25).",
        safety="none",
    )


def respond(
    question: str,
    user_id: str = "synthetic-maya",
    mode: Literal["education", "summary"] = "education",
) -> AgentResponse:
    est = estimate_phase(user_id)

    # Safety rules decide first (CLAUDE.md), even over the fertility guard: a message that's both
    # fertility-timing and a red flag ("when's my fertile window? also I passed out") must escalate.
    result = safety.assess(safety.extract_facts(question))
    if result.safety == "red_flag":
        return _red_flag_response(mode, result)

    if is_fertility_timing(question):
        return _fertility_decline(mode, est)

    if mode == "summary":
        return stub_respond(question, user_id, mode).model_copy(update={"safety": result.safety})

    evidence, fallback_used = _retrieve(question, {"phase": est.phase})
    evidence = strip_fertility_timing(evidence)
    return AgentResponse(
        mode=mode,
        text=_education_text(question, evidence, fallback_used),
        evidence_chips=evidence,
        data_chips=[_phase_chip(est)],
        uncertainty_note=_uncertainty_note(est),
        safety=result.safety,
        fallback_used=fallback_used,
    )
