import pytest

from agent import router, safety
from agent.fertility_guard import is_fertility_timing, strip_fertility_timing
from agent.stub import respond as stub_respond
from contracts import AgentResponse, Evidence


def test_stub_matches_contract():
    """agent.stub stays the canned-fallback source agent.router falls back to."""
    for mode in ("education", "summary"):
        r = stub_respond("why am I tired?", mode=mode)
        assert isinstance(r, AgentResponse) and r.mode == mode
        assert r.uncertainty_note
    assert stub_respond("why am I tired?").evidence_chips  # education answers cite sources


def _evidence(snippet: str) -> Evidence:
    return Evidence(
        doc_id="d",
        chunk_id="d#0",
        source_org="Org",
        title="Title",
        url="https://example.org",
        snippet=snippet,
        retrieved_at="2026-11-16T00:00:00Z",
    )


# --- fertility guard (D25) -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "what are my fertile days this cycle",
        "whats the best time to try to conceive",
        "can you use an ovulation calculator for me",
        "are there any safe days for me this week",
    ],
)
def test_fertility_timing_questions_are_flagged(text):
    assert is_fertility_timing(text)


def test_an_ordinary_cycle_question_is_not_flagged():
    assert not is_fertility_timing("why do I feel so tired this week")


def test_strip_fertility_timing_drops_only_matching_snippets():
    kept = _evidence("Your temperature rises slightly after ovulation.")
    dropped = _evidence("The fertile window is the best time to try to conceive.")
    assert strip_fertility_timing([kept, dropped]) == [kept]


def test_router_declines_fertility_timing_before_retrieving(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("retrieval should not run for a fertility-timing question")

    monkeypatch.setattr(router, "live_retrieve", boom)
    monkeypatch.setattr(router, "canned_retrieve", boom)
    r = router.respond("what are my fertile days", mode="education")
    assert r.safety == "none"
    assert "doesn't do fertility timing" in r.text
    assert r.evidence_chips == []


# --- safety rules (D5 / D29) ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "i've been soaking through a pad every hour since this morning",
        "passing clots bigger than a quarter the last two hours",
    ],
)
def test_heavy_bleeding_is_red_flag(text):
    result = safety.assess(safety.extract_facts(text))
    assert result.safety == "red_flag"


def test_tss_combo_is_red_flag_without_a_temperature():
    text = "i have a weird rash and feel sick to my stomach, used a tampon today and feel dizzy"
    facts = safety.extract_facts(text)
    assert facts.reported_temp_f is None
    assert safety.assess(facts).safety == "red_flag"


def test_lone_rash_with_tampon_is_red_flag():
    """FDA lists each TSS sign as independently actionable, not a required combination."""
    result = safety.assess(safety.extract_facts("i have a weird rash and i used a tampon today"))
    assert result.safety == "red_flag"


def test_a_rash_with_no_tampon_mention_is_not_flagged_as_tss():
    result = safety.assess(safety.extract_facts("i have a rash on my arm"))
    assert result.safety == "none"


def test_a_bare_fever_number_is_red_flag_without_feverish_wording():
    result = safety.assess(safety.extract_facts("i had a fever last night, around 101"))
    assert result.safety == "red_flag"


def test_feeling_feverish_alone_asks_rather_than_concludes():
    """Caution, not red_flag — the rule's own text says it isn't enough to judge (Selina, #7)."""
    result = safety.assess(safety.extract_facts("i feel kind of warm today, is that normal"))
    assert result.safety == "caution"
    assert "temperature" in result.reason.lower()


def test_feeling_hot_after_exercise_is_not_a_false_red_flag():
    text = "i feel hot after my run, is that normal in my luteal phase"
    result = safety.assess(safety.extract_facts(text))
    assert result.safety != "red_flag"


def test_confirmed_fever_with_dizziness_is_red_flag():
    text = "i had a fever last night, around 101, and today im really dizzy"
    result = safety.assess(safety.extract_facts(text))
    assert result.safety == "red_flag"


def test_amenorrhea_90_days_not_pregnant_is_red_flag():
    text = "i havent gotten my period in like 120 days, im not pregnant"
    result = safety.assess(safety.extract_facts(text))
    assert result.safety == "red_flag"


def test_amenorrhea_excluded_when_pregnant():
    text = "i havent had my period in 100 days but i am pregnant"
    result = safety.assess(safety.extract_facts(text))
    assert result.safety != "red_flag"


def test_pcos_pattern_is_caution_not_red_flag():
    text = "my cycles have been so irregular the last 3 months, all over the place"
    result = safety.assess(safety.extract_facts(text))
    assert result.safety == "caution"


def test_missed_two_pills_is_caution():
    result = safety.assess(safety.extract_facts("i missed 2 pills in a row this week"))
    assert result.safety == "caution"


def test_ordinary_question_is_none():
    result = safety.assess(safety.extract_facts("how long should a normal cycle be"))
    assert result.safety == "none"


# --- regression cases from Selina's PR #10 review -----------------------------


def test_router_prioritizes_a_red_flag_over_the_fertility_decline(monkeypatch):
    """Selina #1: safety rules decide first, even when the message is also fertility-timing."""
    monkeypatch.setattr(router, "live_retrieve", lambda *a, **k: [])
    r = router.respond(
        "when is my fertile window? also I passed out this morning", mode="education"
    )
    assert r.safety == "red_flag"


def test_amenorrhea_prefers_the_count_near_the_period_phrase():
    """Selina #2: an unrelated "N days" elsewhere shouldn't beat the real period gap."""
    text = "i haven't had my period in 4 months and i've been exhausted for 3 days"
    result = safety.assess(safety.extract_facts(text))
    assert result.safety == "red_flag"


def test_a_pregnancy_question_does_not_suppress_the_amenorrhea_rule():
    """Selina #3: "could I be pregnant?" is a question, not an affirmation."""
    text = "could i be pregnant? i haven't had a period in 4 months"
    result = safety.assess(safety.extract_facts(text))
    assert result.safety == "red_flag"


@pytest.mark.parametrize(
    "text",
    [
        "i have a fever of 39",
        "my temperature is 38.9 and i feel awful",
    ],
)
def test_celsius_fevers_are_recognized(text):
    """Selina #4: a bare number below ~50 can't be a real Fahrenheit fever, so it's Celsius."""
    result = safety.assess(safety.extract_facts(text))
    assert result.safety == "red_flag"


@pytest.mark.parametrize(
    "text",
    [
        "i have severe cramps and ibuprofen didn't help",
        "my cramps are unbearable",
    ],
)
def test_cramps_count_as_pain(text):
    """Selina #5: "cramps" is the common phrasing, not just "pain"."""
    result = safety.assess(safety.extract_facts(text))
    assert result.safety == "red_flag"


def test_tampon_plural_is_recognized():
    """Selina #6: `\\btampon\\b` didn't match "tampons"."""
    result = safety.assess(safety.extract_facts("i have a rash and i use tampons"))
    assert result.safety == "red_flag"


def test_negated_soaking_is_not_a_false_alarm():
    """Selina #8, lower priority: negation on the soaking rule too."""
    result = safety.assess(
        safety.extract_facts("i'm not soaking through pads, just a normal period")
    )
    assert result.safety != "red_flag"


# --- router integration ---------------------------------------------------------


def test_router_short_circuits_on_red_flag_without_calling_retrieval(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("retrieval should not run when a rule already fired")

    monkeypatch.setattr(router, "live_retrieve", boom)
    monkeypatch.setattr(router, "canned_retrieve", boom)
    r = router.respond("i've been soaking through a pad every hour", mode="education")
    assert r.safety == "red_flag"
    assert r.escalation is not None


def test_router_falls_back_to_canned_evidence_when_the_corpus_is_missing(monkeypatch):
    def empty_corpus(*a, **k):
        raise RuntimeError("Corpus is empty. Run: python -m rag.corpus")

    monkeypatch.setattr(router, "live_retrieve", empty_corpus)
    r = router.respond("why do I feel so tired this week", mode="education")
    assert r.fallback_used is True
    assert r.safety == "none"


def test_router_caution_question_still_answers(monkeypatch):
    monkeypatch.setattr(router, "live_retrieve", lambda *a, **k: [])
    r = router.respond("i missed 2 pills in a row, what should i do", mode="education")
    assert r.safety == "caution"
