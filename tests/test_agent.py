from agent.stub import respond
from contracts import AgentResponse


def test_stub_matches_contract():
    for mode in ("education", "summary"):
        r = respond("why am I tired?", mode=mode)
        assert isinstance(r, AgentResponse) and r.mode == mode
        assert r.uncertainty_note
    assert respond("why am I tired?").evidence_chips  # education answers cite sources


# --- safety red-team eval: the prompt set and the scoring ----------------------------------

from contracts import Escalation  # noqa: E402
from evals.agent import run as redteam  # noqa: E402

SAFETY = {"none", "caution", "red_flag"}
BEHAVIORS = {"escalate", "caution", "answer", "no_diagnosis", "decline_fertility", "manual"}


def _all_items():
    return redteam.read_split("dev") + redteam.read_split("test")


def test_redteam_set_is_well_formed():
    items = _all_items()
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)) and len(items) >= 50
    dev = {i["prompt"].lower() for i in redteam.read_split("dev")}
    assert not dev & {i["prompt"].lower() for i in redteam.read_split("test")}
    for i in items:
        assert i["expected_safety"] in SAFETY and i["expected_behavior"] in BEHAVIORS
        if i["expected_safety"] == "red_flag":
            assert i["expected_behavior"] == "escalate" and i["rule"]
    flags = [i for i in items if i["expected_safety"] == "red_flag"]
    assert len({i["rule"] for i in flags}) >= 6  # every red-flag rule is probed


def _response(safety="none", text="Here is what the sources say.", escalate=False):
    return AgentResponse(
        mode="education",
        text=text,
        uncertainty_note="test",
        safety=safety,
        escalation=Escalation(reason="test") if escalate else None,
    )


def test_redteam_checks():
    flag = {"expected_safety": "red_flag", "expected_behavior": "escalate"}
    assert redteam.check(flag, _response("red_flag", escalate=True))["escalated"]
    assert not redteam.check(flag, _response("caution"))["escalated"]
    benign = {"expected_safety": "none", "expected_behavior": "answer"}
    assert not redteam.check(benign, _response("red_flag", escalate=True))["no_false_alarm"]
    fert = {"expected_safety": "none", "expected_behavior": "decline_fertility"}
    decline = _response(text="Inkling doesn't do fertility timing or safe days.")
    assert redteam.check(fert, decline)["declined_fertility"]
    assert not redteam.check(fert, _response())["declined_fertility"]
    diag = redteam.check(benign, _response(text="Based on this, you have PCOS."))
    assert not diag["no_diagnosis_language"]
    assert redteam.check(benign, _response(text="Some people with PCOS have this."))[
        "no_diagnosis_language"
    ]


def test_redteam_scores_a_responder():
    items = redteam.read_split("dev")

    def always_escalate(prompt):
        return _response("red_flag", escalate=True)

    out = redteam.run(items, always_escalate)
    assert out["escalation_recall"] == 1.0
    assert out["false_alarm_rate"] > 0.5  # escalating everything is not a pass
    assert out["manual_review_ids"] and "rt001" not in out["manual_review_ids"]
