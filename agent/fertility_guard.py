"""Fertility-timing guard (D25). No "safe days" or fertile-window content, in or out.

Reuses rag.corpus.FERTILITY_TIMING so the input check, the output check and the indexing-time
flag (sources.md) all agree on what counts.
"""

from contracts import Evidence
from rag.corpus import FERTILITY_TIMING

DECLINE_TEXT = (
    'Inkling doesn\'t do fertility timing or "safe days" — it only interprets your cycle and '
    "the signals your wearable shows. For anything about trying to conceive or avoid pregnancy, "
    "that's worth asking a clinician."
)


def is_fertility_timing(text: str) -> bool:
    return bool(FERTILITY_TIMING.search(text))


def strip_fertility_timing(evidence: list[Evidence]) -> list[Evidence]:
    """Drop any retrieved chunk that reads as fertility-timing, even if the question didn't."""
    return [e for e in evidence if not FERTILITY_TIMING.search(e.snippet)]
