"""Signals entry points used by the app and the agent.

get_daily_records reads the store (signals/store.py). A user with nothing stored yet, such as the
demo user, gets the synthetic fixture, labeled source="synthetic". estimate_phase is still a stub.
"""

from datetime import date

from contracts import DailyRecord, PhaseEstimate, load_fixture
from signals import store


def get_daily_records(user_id: str) -> list[DailyRecord]:
    stored = store.load_daily_records(user_id, date.min, date.max)
    if stored:
        return stored
    return [
        DailyRecord.model_validate({**r, "user_id": user_id}) for r in load_fixture("daily_records")
    ]


def estimate_phase(user_id: str) -> PhaseEstimate:
    return PhaseEstimate.model_validate({**load_fixture("phase_estimate"), "user_id": user_id})
