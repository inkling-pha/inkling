"""Red-flag and caution rules (D5), drafted in docs/safety_rules.md.

Two stages, per D5's second approach: extract_facts() pulls a few structured facts out of free
text, then assess() is a pure function of those facts — the LLM (or whatever extracts facts)
never decides the safety level itself, and can only fail to find a fact, never override one.

extract_facts() here is v1: keyword/regex matching, the explicit fallback-safety-net option in D5,
used because the LLM extractor is blocked on D14 (what reaches the LLM) and D8's model choice.
Swap its body for an LLM call later; assess() and SafetyFacts don't need to change.
"""

import re
from dataclasses import dataclass
from typing import Literal

Safety = Literal["none", "caution", "red_flag"]

_WORDS_TO_NUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "a": 1,
    "an": 1,
    "couple": 2,
    "few": 3,
}


@dataclass(frozen=True)
class SafetyFacts:
    soaking_hourly_or_big_clots: bool = False
    tss_combo: bool = False  # rash + vomiting/diarrhea + dizziness/fainting together
    tss_rash_alone: bool = False  # rash + tampon use, no other sign yet
    feels_feverish: bool = False
    reported_temp_f: float | None = None
    fainting_or_severe_dizziness: bool = False
    days_since_period: int | None = None
    pregnant_breastfeeding_or_perimenopause: bool = False
    severe_unrelieved_pelvic_pain: bool = False
    bleeding_between_periods_or_postmenopause: bool = False
    irregular_cycle_pattern: bool = False
    new_discharge_symptom: bool = False
    missed_pills_in_a_row: int | None = None
    pmdd_level_mood: bool = False


@dataclass(frozen=True)
class SafetyResult:
    safety: Safety
    reason: str | None = None  # user-facing, cites the rule that fired
    citation: str | None = None  # source org/title for the reason, if any


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _affirmed(text: str, *patterns: str, window: int = 15) -> bool:
    """Like _has, but a nearby "not"/"n't"/"no" before the match means it doesn't count.

    Only worth the extra care where getting it backwards would suppress a red flag (missing one
    is the worst failure, D5) — general negation handling is still an LLM-extractor job (D5).
    """
    for p in patterns:
        for m in re.finditer(p, text):
            before = text[max(0, m.start() - window) : m.start()]
            if not re.search(r"\b(not|n't|no)\b\s*$", before):
                return True
    return False


def _number_before(text: str, *units: str) -> int | None:
    """The first integer (digit or small word) right before one of these unit words."""
    unit_group = "|".join(units)
    m = re.search(rf"(\d+|{'|'.join(_WORDS_TO_NUM)})\s+({unit_group})", text)
    if not m:
        return None
    raw = m.group(1)
    return int(raw) if raw.isdigit() else _WORDS_TO_NUM[raw]


def extract_facts(text: str) -> SafetyFacts:
    """v1 keyword extraction. Conservative: only sets a fact when the text is fairly explicit."""
    t = text.lower()

    soaking = _has(
        t,
        r"soak(ing|ed)?\s+(a |an |through a |through )?(pad|tampon)",
        r"(pad|tampon)s?\s+every\s+hour",
        r"clots?\s+(bigger|larger)\s+than\s+a\s+quarter",
    )
    rash = _has(t, r"\brash\b")
    gi = _has(
        t, r"vomit|throwing up|threw up|diarrh?ea|nausea(ted)?|stomach ?ache|sick to my stomach"
    )
    faint_or_dizzy = _has(
        t, r"faint(ed|ing)?|pass(ed|ing)? out|black(ed)? out|dizz(y|iness)|light.?headed"
    )
    tampon = _has(t, r"\btampon\b")
    # FDA's tampon-safety page lists sudden high fever, rash, vomiting, diarrhea, and
    # fainting/dizziness as TSS signs, any one of which alone is "seek medical attention
    # immediately" — not a required combination. A lone rash during tampon use gets its own
    # red_flag below; fainting/dizziness alone already has its own rule further down.
    tss_combo = rash and gi and faint_or_dizzy
    tss_rash_alone = rash and tampon and not tss_combo

    feels_feverish = _has(
        t, r"feverish|running a fever|have a fever|feel(ing)?\b.{0,20}\b(warm|hot|feverish)\b"
    )
    temp_match = (
        re.search(r"(\d{2,3}(?:\.\d)?)\s*(?:°|degrees)?\s*f\b", t)
        or re.search(r"temp(erature)?.{0,15}?(\d{2,3}(?:\.\d)?)", t)
        or re.search(r"fever.{0,30}?(\d{2,3}(?:\.\d)?)", t)
    )
    reported_temp = None
    if temp_match:
        digits = next(g for g in reversed(temp_match.groups()) if g and re.match(r"^\d", g))
        reported_temp = float(digits)
    # A reported number is its own evidence — FDA's TSS fever sign (102°F+) and the CDC general
    # threshold (100.4°F) don't require "feverish" wording too.
    feels_feverish = feels_feverish or (reported_temp is not None and reported_temp >= 100.4)

    days_since = _number_before(t, "days?")
    months_since = _number_before(t, "months?")
    if months_since is not None and days_since is None:
        days_since = months_since * 30
    no_period_context = _has(t, r"no period|haven'?t (had|gotten) (my |a )?period|missed my period")

    excludes_amenorrhea_rule = _affirmed(t, r"pregnan|breastfeed|nursing|perimenopaus|menopaus")

    severe_pain = _has(
        t,
        r"severe (pelvic|abdominal)? ?pain",
        r"pain.{0,20}(can'?t function|won'?t stop|unbearable)",
    )
    otc_no_help = _has(
        t,
        r"(advil|ibuprofen|tylenol|midol|otc|pain reliever|medication)"
        r".{0,20}(didn'?t|doesn'?t|not).{0,10}help",
    )

    between_periods = _has(
        t,
        r"between (my )?periods?",
        r"bleeding after menopause",
        r"post.?menopaus(e|al).{0,15}bleed",
    )

    # Phrase-matched only — v1 doesn't parse stated cycle lengths into numbers. OWH's own page
    # calls 24-38 days normal, so a numeric version of this rule should use 38+, not the 21-35
    # folk range.
    irregular = _has(
        t,
        r"irregular.{0,20}(months|cycle)",
        r"cycles?.{0,20}(all over|varying|unpredictable|different (lengths|every))",
    )

    discharge = _has(t, r"discharge") and _has(
        t, r"color|odor|smell|grey|gray|texture|different|weird|unusual"
    )

    missed_pills = _number_before(t, "pills?")
    if missed_pills is not None and not _has(t, r"missed|forgot|skip"):
        missed_pills = None

    pmdd = _has(t, r"mood.{0,20}(disrupt|can'?t function|out of control)", r"pmdd")

    return SafetyFacts(
        soaking_hourly_or_big_clots=soaking,
        tss_combo=tss_combo,
        tss_rash_alone=tss_rash_alone,
        feels_feverish=feels_feverish and not tss_combo,
        reported_temp_f=reported_temp,
        fainting_or_severe_dizziness=faint_or_dizzy and not tss_combo,
        days_since_period=days_since if no_period_context else None,
        pregnant_breastfeeding_or_perimenopause=excludes_amenorrhea_rule,
        severe_unrelieved_pelvic_pain=severe_pain and (otc_no_help or "severe" in t),
        bleeding_between_periods_or_postmenopause=between_periods,
        irregular_cycle_pattern=irregular,
        new_discharge_symptom=discharge,
        missed_pills_in_a_row=missed_pills,
        pmdd_level_mood=pmdd,
    )


def assess(facts: SafetyFacts) -> SafetyResult:
    """Rules decide. Checked in docs/safety_rules.md's order; first red_flag hit wins."""
    if facts.soaking_hourly_or_big_clots:
        return SafetyResult(
            "red_flag",
            "Soaking a pad or tampon every hour for 2+ hours, or clots bigger than a quarter, "
            "is heavy enough to need same-day care.",
            "CDC: About heavy menstrual bleeding",
        )
    if facts.tss_combo:
        return SafetyResult(
            "red_flag",
            "A rash with vomiting or diarrhea and dizziness or fainting together is a toxic "
            "shock syndrome warning pattern, especially with a tampon in. This needs care now, "
            "with or without a fever.",
            "FDA: The facts on tampons and tampon safety",
        )
    if facts.tss_rash_alone:
        return SafetyResult(
            "red_flag",
            "A sunburn-like rash during or soon after tampon use is itself a toxic shock "
            "syndrome warning sign, even with nothing else going on — FDA says to stop using "
            "the tampon and get care now, not wait for other symptoms.",
            "FDA: The facts on tampons and tampon safety",
        )
    if facts.feels_feverish and facts.reported_temp_f is None:
        return SafetyResult(
            "red_flag",
            "Feeling feverish is worth checking rather than guessing at — what's your temperature "
            "if you've taken it? Without a number or another sign, this isn't enough to judge.",
            None,
        )
    if facts.reported_temp_f is not None and facts.reported_temp_f >= 100.4:
        return SafetyResult(
            "red_flag",
            f"A temperature of {facts.reported_temp_f:.0f}°F during your period, especially with "
            "feeling unwell, is worth same-day care.",
            "FDA tampon safety (102°F+ is a TSS sign) / CDC's general fever threshold (100.4°F)",
        )
    if facts.fainting_or_severe_dizziness:
        return SafetyResult(
            "red_flag",
            "Fainting or severe dizziness during a period needs same-day care.",
            "CDC: About heavy menstrual bleeding / OWH: Period problems",
        )
    if (
        facts.days_since_period is not None
        and facts.days_since_period >= 90
        and not (facts.pregnant_breastfeeding_or_perimenopause)
    ):
        return SafetyResult(
            "red_flag",
            "No period for 90+ days, without pregnancy, breastfeeding or perimenopause to explain "
            "it, is worth a clinician's look.",
            "OWH: Your menstrual cycle (verbatim: \"if you don't have a period for 90 days "
            "(three months)... talk to your doctor\"). NICHD's own threshold is 6 months / 3 "
            "periods in a row, stricter than this.",
        )
    if facts.severe_unrelieved_pelvic_pain:
        return SafetyResult(
            "red_flag",
            "Severe pelvic or abdominal pain that stops your normal activities and doesn't ease "
            "with OTC pain relief needs a clinician, not chat.",
            "OWH: Period problems",
        )
    if facts.bleeding_between_periods_or_postmenopause:
        return SafetyResult(
            "red_flag",
            "Heavy or persistent bleeding between periods, or any bleeding after menopause, is "
            "worth getting checked.",
            "OWH: Period problems",
        )

    if facts.irregular_cycle_pattern:
        return SafetyResult(
            "caution",
            "Cycles outside the usual 24-38 day range, or irregular for a few months, are worth "
            "mentioning to a clinician.",
            "OWH: Your menstrual cycle (24-38 days is the stated normal range) / "
            "OWH & NICHD PCOS pages (irregular periods is a listed PCOS symptom, no cycle-length "
            "number given there)",
        )
    if facts.new_discharge_symptom:
        return SafetyResult(
            "caution",
            "New discharge with a different color, texture or odor — without a fever or severe "
            "pain — is worth asking a clinician about.",
            "CDC: Bacterial vaginosis / NICHD: vaginitis symptoms",
        )
    if facts.missed_pills_in_a_row is not None and facts.missed_pills_in_a_row >= 2:
        return SafetyResult(
            "caution",
            "Missing 2 or more combined pills in a row changes what you should do next — worth a "
            "quick check with a clinician or pharmacist.",
            "CDC US SPR: combined hormonal contraceptives (the specific missed-pills flowchart "
            "doc cited originally was dropped from rag/manifest.csv in a later cleanup; this "
            "page's missed-pill guidance hasn't been re-verified against the new doc)",
        )
    if facts.pmdd_level_mood:
        return SafetyResult(
            "caution",
            "Mood, sleep or energy changes that disrupt daily life beyond the usual PMS window are "
            "worth bringing up with a clinician.",
            "OWH: Premenstrual dysphoric disorder (PMDD)",
        )

    return SafetyResult("none")
