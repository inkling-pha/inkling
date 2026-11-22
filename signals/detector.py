"""Baselines + a look-back detector for the post-ovulation rise (D15 rules, D34 look-back only).

For each day, every signal is compared with her own usual level:
- **baseline** = median of the previous BASELINE_DAYS nights (about one cycle, so it sits between
  her lower follicular and higher luteal levels);
- **recent** = median of the last RECENT_DAYS nights, today included.

A signal votes "luteal-like" when recent is past baseline by its threshold in the luteal direction
(temperature and resting HR up, HRV down), "not" when it is past by the threshold the other way,
and abstains in between or when it has too few nights. The day's verdict is the sign of the votes:
True (luteal-like), False, or None ("not enough data yet"). Only past and present nights are used,
so it describes what already happened and never predicts a date.

Thresholds start at half the mcPHASES luteal-vs-follicular differences (docs/data.md: RHR +2.5
bpm, temperature +0.23 C, HRV -5.4 ms), because the baseline sits about halfway between the two
phases. The held-out eval (evals/signals/run.py) tunes them on training participants only.

Signals-internal: the app and agent see this only through PhaseEstimate, once it is wired into
estimate_phase.
"""

import statistics
from datetime import date, timedelta
from typing import NamedTuple

from contracts import DailyRecord

BASELINE_DAYS = 28
RECENT_DAYS = 3
MIN_BASELINE_NIGHTS = 10
MIN_RECENT_NIGHTS = 2

# field -> (direction in the luteal phase, starting threshold in the field's units)
SIGNALS: dict[str, tuple[int, float]] = {
    "skin_temp_dev_c": (+1, 0.10),
    "rhr_bpm": (+1, 1.0),
    "hrv_rmssd_ms": (-1, 2.5),
}


class DayState(NamedTuple):
    """One day's detector output. Signals-internal, not a contract."""

    date: date
    luteal_like: bool | None  # None = not enough data yet, or the signals disagree
    deltas: dict[str, float]  # recent minus baseline, per signal with enough nights
    votes: dict[str, int]  # +1 luteal-like, -1 not, 0 in between, per signal with a delta


def _median_in(values: dict[date, float], start: date, end: date, minimum: int) -> float | None:
    """Median of the values dated start..end inclusive, or None with fewer than `minimum`."""
    window = [v for d, v in values.items() if start <= d <= end]
    return statistics.median(window) if len(window) >= minimum else None


def detect(
    records: list[DailyRecord],
    signals: dict[str, tuple[int, float]] | None = None,
    baseline_days: int = BASELINE_DAYS,
    recent_days: int = RECENT_DAYS,
) -> list[DayState]:
    """One DayState per record date, for one user's records (any order, gaps allowed)."""
    signals = SIGNALS if signals is None else signals
    series = {
        field: {r.date: getattr(r, field) for r in records if getattr(r, field) is not None}
        for field in signals
    }
    states = []
    for day in sorted({r.date for r in records}):
        recent_start = day - timedelta(days=recent_days - 1)
        deltas, votes = {}, {}
        for field, (direction, threshold) in signals.items():
            values = series[field]
            base = _median_in(
                values,
                recent_start - timedelta(days=baseline_days),
                recent_start - timedelta(days=1),
                MIN_BASELINE_NIGHTS,
            )
            recent = _median_in(values, recent_start, day, MIN_RECENT_NIGHTS)
            if base is None or recent is None:
                continue
            delta = recent - base
            deltas[field] = delta
            signed = direction * delta
            votes[field] = 1 if signed > threshold else -1 if signed < -threshold else 0
        total = sum(votes.values())
        verdict = None if total == 0 else total > 0
        states.append(DayState(day, verdict, deltas, votes))
    return states
