"""Agent layer stub: wires the signals and rag stubs into an AgentResponse.

agent.router now handles "education" for real (fertility guard + red-flag rules, D5/D25) and
calls this stub only as retrieval's canned fallback. "summary" mode still comes from here
unchanged: a real summary agent needs D7 (routing) and D14 (what reaches the LLM) settled first.
"""

from typing import Literal

from contracts import AgentResponse, DataChip
from rag.stub import retrieve
from signals.stub import estimate_phase


def respond(
    question: str,
    user_id: str = "synthetic-maya",
    mode: Literal["education", "summary"] = "education",
) -> AgentResponse:
    est = estimate_phase(user_id)
    evidence = retrieve(question, {"phase": est.phase}) if mode == "education" else []
    window = est.ovulation_window
    return AgentResponse(
        mode=mode,
        text=f"STUB {mode} answer to: {question!r}",
        evidence_chips=evidence,
        data_chips=[
            DataChip(
                label="Estimated phase",
                value=f"{est.phase} (day {est.cycle_day})",
                chart_ref=est.chart_ref,
                source=est.source,
            )
        ],
        uncertainty_note=(
            f"Ovulation window {window.start} to {window.end}, confidence {est.confidence:.2f}."
            if window
            else "Not enough data yet to estimate ovulation."
        ),
        safety="none",
    )
