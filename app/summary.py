"""Turns contract objects into the words on screen. No Streamlit here, so it's easy to test.

Wording follows the safety stance in CLAUDE.md and D25/D27: describe the recorded change first,
name other explanations, and state the limit. slides-08 p.27: confidence stays a word (no number
or bar) until its meaning is validated in the Sprint 2 eval.
"""

from datetime import date

from contracts import DailyRecord, PhaseEstimate

PHASE_LABELS = {
    "menstrual": "Likely period",
    "follicular": "Likely follicular",
    "ovulatory": "Near likely window",
    "luteal": "Likely luteal",
    "unknown": "Phase unclear",
}
LIMIT = "An estimate, not a test. Accuracy not validated yet. Not for birth control or timing."


def long_date(d: date) -> str:
    return f"{d:%a %b} {d.day}"


def short_date(d: date) -> str:
    return f"{d:%b} {d.day}"


def phase_label(est: PhaseEstimate) -> str:
    return PHASE_LABELS[est.phase]


def window_text(est: PhaseEstimate) -> str | None:
    window = est.ovulation_window
    if window is None:
        return None
    if window.start.month == window.end.month:
        return f"{short_date(window.start)}–{window.end.day}"
    return f"{short_date(window.start)}–{short_date(window.end)}"


def confidence_word(confidence: float) -> str:
    if confidence < 0.4:
        return "Low"
    return "Medium" if confidence < 0.7 else "Higher"


def coverage_line(est: PhaseEstimate, records: list[DailyRecord]) -> str:
    """Source, coverage and dates. Coverage is what arrived, not a confidence score (p.26)."""
    origin = "Synthetic" if est.source == "synthetic" else est.source.capitalize()
    if not records:
        return f"{origin} Fitbit data · no nights recorded"
    recorded = sum(r.skin_temp_dev_c is not None for r in records)
    span = f"{short_date(records[0].date)}–{short_date(records[-1].date)}"
    return f"{origin} Fitbit data · {recorded} of {len(records)} nights recorded, {span}"


def warm_streak(records: list[DailyRecord]) -> int:
    """Recorded nights in a row, newest first, above her usual. Missing nights are skipped."""
    streak = 0
    for record in reversed(records):
        if record.skin_temp_dev_c is None:
            continue
        if record.skin_temp_dev_c <= 0:
            break
        streak += 1
    return streak


def today_summary(est: PhaseEstimate, records: list[DailyRecord]) -> tuple[str, str]:
    """(headline, body) for the Today card."""
    window = window_text(est)
    if window is None:
        return (
            "Not enough data yet",
            "Inkling needs more nights before it can show a likely window. "
            "Wearing your Fitbit tonight will help.",
        )
    level = f"{confidence_word(est.confidence)} confidence. Likely window {window}."
    streak = warm_streak(records)
    if streak >= 2:
        return (
            f"Skin temp above your usual for {streak} nights",
            f"That pattern often follows ovulation. {level} "
            "Stress, sleep or getting sick can look similar.",
        )
    return (
        "Too early to tell",
        f"{streak or 'No'} warm night{'' if streak == 1 else 's'} isn’t a pattern yet. {level}",
    )
