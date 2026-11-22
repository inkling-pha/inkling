"""Signals entry points used by the app and the agent.

Both read the store (signals/store.py). The demo user, "synthetic-maya", reads the synthetic
persona instead (signals/synthetic.py), dated so her last day is today; her data never goes in the
store. Any other user with nothing stored yet gets the synthetic fixtures. Everything synthetic is
labeled source="synthetic". estimate_phase is a calendar count from logged periods
(signals/cycle.py).
"""

from datetime import date

from contracts import DailyRecord, PhaseEstimate, load_fixture
from signals import cycle, store, synthetic


def get_daily_records(user_id: str) -> list[DailyRecord]:
    if user_id == synthetic.USER_ID:
        return synthetic.load()
    stored = store.load_daily_records(user_id, date.min, date.max)
    if stored:
        return stored
    return [
        DailyRecord.model_validate({**r, "user_id": user_id}) for r in load_fixture("daily_records")
    ]


def estimate_phase(user_id: str) -> PhaseEstimate:
    if user_id == synthetic.USER_ID:
        records = synthetic.load()
        return cycle.estimate_phase(
            user_id,
            today=records[-1].date,
            checkins={r.date: r.checkin for r in records if r.checkin},
            source="synthetic",
        )
    if store.data_sources(user_id):
        return cycle.estimate_phase(user_id)
    return PhaseEstimate.model_validate({**load_fixture("phase_estimate"), "user_id": user_id})
