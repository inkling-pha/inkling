"""Cycle history and a calendar phase estimate, from the bleeding the user logs in check-ins.

- A period starts on a day of light, medium or heavy bleeding with no such day in the
  MIN_GAP_DAYS before it. Spotting alone never starts a period (it can be mid-cycle).
- A period runs from its start through later bleeding days, spotting included, as long as they are
  at most PERIOD_SKIP_DAYS apart (one unlogged day is allowed).
- Her usual cycle and period lengths are the medians of her last HISTORY_CYCLES, once she has
  MIN_OWN_CYCLES of them; until then the population defaults are used.
- The phase is a calendar count, so it is always "Low" confidence (D28) until the held-out eval
  measures it. With no period start, or past her usual length plus a margin, it is "unknown".
- The ovulation day is estimated only to place the phase boundaries. `ovulation_est_date` and
  `ovulation_window` stay None: no fertility timing leaves signals (D25, D27).
- Birth control logged in the last BC_LOOKBACK_DAYS makes the phase "unknown": many methods stop
  ovulation, and the bleed in a pill break is not a period. Period tracking is unaffected.

Defaults come from the mcPHASES cycle check (see docs/data.md).
"""

from datetime import date, timedelta
from itertools import pairwise
from statistics import median

from contracts import CheckIn, PhaseEstimate
from contracts.models import Phase
from signals import store

FLOW = {"light", "medium", "heavy"}  # bleeding that can start a period
BLEEDING = FLOW | {"spot"}
MIN_GAP_DAYS = 10  # days since the last flow day before flow counts as a new period (mcPHASES)
PERIOD_SKIP_DAYS = 2  # bleeding days this close together belong to the same period
DEFAULT_CYCLE_DAYS = 29  # mcPHASES median cycle
DEFAULT_PERIOD_DAYS = 6  # mcPHASES median period
HISTORY_CYCLES = 6  # her usual lengths are the medians of this many recent cycles
MIN_OWN_CYCLES = 2  # fewer than this and the defaults are used
STALE_DAYS = 14  # no bleeding answer for this long: days since the last period is unknown
LATE_MARGIN_DAYS = 7  # past her usual length plus this, the phase is unknown
MAX_CYCLE_DAYS = 38  # past this, the phase is unknown whatever her usual length
LUTEAL_DAYS = 12  # estimated ovulation day = usual cycle length - this (textbook 14, Mira ~10-11)
OVULATORY_HALF_WIDTH = 1  # days either side of the estimated ovulation day labeled "ovulatory"
BC_LOOKBACK_DAYS = 35  # about one pill pack plus a margin
CALENDAR_CONFIDENCE = 0.3  # shows as "Low"; set from the held-out eval later (D28)


def _checkins(user_id: str, today: date) -> dict[date, CheckIn]:
    return store.load_checkins(user_id, date.min, today + timedelta(days=1))


def _periods(checkins: dict[date, CheckIn]) -> list[tuple[date, date]]:
    """(first day, last logged bleeding day) of each period, oldest first."""
    found: list[list[date]] = []
    last_flow = None
    for day in sorted(checkins):
        bleeding = checkins[day].bleeding
        if bleeding in FLOW and (last_flow is None or (day - last_flow).days >= MIN_GAP_DAYS):
            found.append([day, day])
        elif bleeding in BLEEDING and found and (day - found[-1][1]).days <= PERIOD_SKIP_DAYS:
            found[-1][1] = day
        if bleeding in FLOW:
            last_flow = day
    return [(start, end) for start, end in found]


def _cycle_lengths(found: list[tuple[date, date]]) -> list[int]:
    return [(b[0] - a[0]).days for a, b in pairwise(found)]


def _usual(lengths: list[int], default: int) -> int:
    recent = lengths[-HISTORY_CYCLES:]
    return round(median(recent)) if len(recent) >= MIN_OWN_CYCLES else default


def periods(user_id: str, today: date | None = None) -> list[tuple[date, date]]:
    """Her logged periods as (first day, last bleeding day), oldest first. The last may be going."""
    return _periods(_checkins(user_id, today or date.today()))


def cycle_lengths(user_id: str, today: date | None = None) -> list[int]:
    """Days from each period start to the next, oldest first. Assumes she logs every period."""
    return _cycle_lengths(periods(user_id, today))


def days_since_last_period(user_id: str, today: date | None = None) -> int | None:
    """Days since her last period started (0 on day 1).

    None when no start is logged, or when she hasn't answered the bleeding question in STALE_DAYS:
    not logging is not the same as not bleeding.
    """
    today = today or date.today()
    checkins = _checkins(user_id, today)
    answered = [d for d, c in checkins.items() if c.bleeding is not None]
    found = _periods(checkins)
    if not found or (today - max(answered)).days > STALE_DAYS:
        return None
    return (today - found[-1][0]).days


def _phase(cycle_day: int, usual_cycle: int, period_days: int) -> Phase:
    if cycle_day > min(usual_cycle + LATE_MARGIN_DAYS, MAX_CYCLE_DAYS):
        return "unknown"  # later than usual: don't wrap into a new cycle
    if cycle_day <= period_days:
        return "menstrual"
    ovulation_day = usual_cycle - LUTEAL_DAYS
    if abs(cycle_day - ovulation_day) <= OVULATORY_HALF_WIDTH:
        return "ovulatory"
    return "follicular" if cycle_day < ovulation_day else "luteal"


def estimate_phase(user_id: str, today: date | None = None) -> PhaseEstimate:
    """Calendar phase from her logged periods; "unknown" when there is nothing to count from."""
    today = today or date.today()
    checkins = _checkins(user_id, today)
    found = _periods(checkins)
    sources = store.data_sources(user_id)
    estimate = PhaseEstimate(
        user_id=user_id,
        as_of=today,
        phase="unknown",
        confidence=0.0,
        method="calendar",
        source=sources.pop() if len(sources) == 1 else "mixed" if sources else "real",
        chart_ref="cycle_clock",
    )
    on_bc = any(c.bc_taken and (today - d).days < BC_LOOKBACK_DAYS for d, c in checkins.items())
    if not found or on_bc:
        return estimate

    # Only finished periods set her usual length: the latest may still be going.
    done = [(e - s).days + 1 for s, e in found if (today - e).days > PERIOD_SKIP_DAYS]
    usual_cycle = _usual(_cycle_lengths(found), DEFAULT_CYCLE_DAYS)
    last_start, last_end = found[-1]
    cycle_day = (today - last_start).days + 1
    # Still bleeding past her usual length counts as menstrual.
    period_days = max(_usual(done, DEFAULT_PERIOD_DAYS), (last_end - last_start).days + 1)
    phase = _phase(cycle_day, usual_cycle, period_days)
    return estimate.model_copy(
        update={
            "phase": phase,
            "cycle_day": cycle_day,
            "confidence": 0.0 if phase == "unknown" else CALENDAR_CONFIDENCE,
            "signals_used": ["checkins"],
        }
    )
