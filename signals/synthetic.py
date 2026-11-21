"""Synthetic Maya: the clearly labeled demo persona, generated from mcPHASES *aggregates* only.

Maya is 20, her periods are hard to predict, and she wears a Fitbit (PRODUCT.md). This builds her
nights and check-ins: four finished cycles of 27-36 days plus a current cycle that is running late,
the setup for the hero question "My period is late again and I'm exhausted."

Where the numbers come from (docs/data.md, aggregates only; no participant's series is used):
- luteal vs follicular: skin temperature +0.23 C, resting HR +2.5 bpm, HRV -5.4 ms;
- typical levels: RHR ~67 bpm, HRV ~48 ms, sleep ~400 min, steps ~5,700 a day;
- periods ~6 days, flow mostly light to medium.
Day-to-day noise and ~10% missed nights make it look like a real wearable, so the detector has to
work for it rather than read a perfect step.

Every record is source="synthetic". The truth (phase and cycle day per date) is for tests only:
never show it in the app, and never treat it as a prediction (D25, D27, D34).

    python -m signals.synthetic                    # writes data/synthetic/maya.json
    python -m signals.synthetic --end 2026-12-11   # dated to end on showcase day
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from contracts import CheckIn, DailyRecord

USER_ID = "synthetic-maya"
OUT = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "maya.json"
SEED = 20

CYCLE_LENGTHS = [29, 35, 27, 33]  # finished cycles: irregular, all within 27-36
CURRENT_CYCLE_DAY = 34  # today; her usual is ~31, so this period counts as late
CURRENT_OVULATION_DAY = 22  # late ovulation explains the late period (look-back only, D34)
LUTEAL_DAYS = 13  # ovulation day = cycle length - this, for the finished cycles
PERIOD_DAYS = 6

# Levels and luteal shifts (from the mcPHASES aggregates above) and day-to-day noise.
BASE = {"skin_temp_dev_c": -0.10, "rhr_bpm": 65.5, "hrv_rmssd_ms": 51.0}
LUTEAL_SHIFT = {"skin_temp_dev_c": 0.23, "rhr_bpm": 2.5, "hrv_rmssd_ms": -5.4}
NOISE_SD = {"skin_temp_dev_c": 0.12, "rhr_bpm": 1.6, "hrv_rmssd_ms": 5.0}
MISSED_NIGHT = 0.10  # watch not worn: every wearable field is None
MISSED_CHECKIN = 0.15  # outside her period; she logs every period day
EXHAUSTED_DAYS = 5  # the last few days: low energy and short sleep

FLOW_BY_DAY = ["medium", "heavy", "medium", "light", "light", "spot"]


def _phase(cycle_day: int, ovulation_day: int) -> str:
    if cycle_day <= PERIOD_DAYS:
        return "menstrual"
    if abs(cycle_day - ovulation_day) <= 1:
        return "ovulatory"
    return "follicular" if cycle_day < ovulation_day else "luteal"


def _cycles() -> list[tuple[int, int]]:
    """(ovulation day, days observed) per cycle; the current one has no end yet."""
    done = [(n - LUTEAL_DAYS, n) for n in CYCLE_LENGTHS]
    return done + [(CURRENT_OVULATION_DAY, CURRENT_CYCLE_DAY)]


def generate(end: date, seed: int = SEED) -> tuple[list[DailyRecord], list[dict]]:
    """Maya's records ending on `end`, plus the per-day truth (tests only)."""
    rng = random.Random(seed)
    total = sum(days for _, days in _cycles())
    day = end - timedelta(days=total - 1)
    records, truth = [], []
    for ovulation_day, days in _cycles():
        for cycle_day in range(1, days + 1):
            phase = _phase(cycle_day, ovulation_day)
            last_days = (end - day).days < EXHAUSTED_DAYS
            records.append(_record(rng, day, cycle_day, phase, last_days))
            truth.append({"date": day.isoformat(), "cycle_day": cycle_day, "phase": phase})
            day += timedelta(days=1)
    return records, truth


def _record(rng: random.Random, day: date, cycle_day: int, phase: str, tired: bool):
    wearable = {}
    if rng.random() >= MISSED_NIGHT:
        luteal = phase == "luteal"
        for field, base in BASE.items():
            value = base + (LUTEAL_SHIFT[field] if luteal else 0) + rng.gauss(0, NOISE_SD[field])
            wearable[field] = round(value, 2 if field == "skin_temp_dev_c" else 1)
        sleep = rng.gauss(345 if tired else 405, 35)
        wearable["sleep_min"] = int(max(180, sleep))
        wearable["steps"] = int(max(500, rng.gauss(5700, 2200)))
    on_period = cycle_day <= PERIOD_DAYS
    checkin = None
    if on_period or rng.random() >= MISSED_CHECKIN:
        pain = rng.choice([4, 5, 6]) if cycle_day <= 2 else rng.choice([0, 0, 1, 2])
        symptoms = ["cramps"] if cycle_day <= 2 else []
        if phase == "luteal" and rng.random() < 0.3:
            symptoms.append("bloating")
        if tired:
            symptoms.append("fatigue")
        checkin = CheckIn(
            energy=rng.choice([1, 2]) if tired else rng.choice([3, 3, 4, 4, 5]),
            bleeding=FLOW_BY_DAY[cycle_day - 1] if on_period else "none",
            pain=pain,
            symptoms=symptoms,
        )
    return DailyRecord(user_id=USER_ID, date=day, checkin=checkin, source="synthetic", **wearable)


def write(end: date, path: Path = OUT, seed: int = SEED) -> Path:
    records, truth = generate(end, seed)
    payload = {
        "about": "Synthetic demo persona 'Maya'. Not a real person. Built from mcPHASES aggregates "
        "only (signals/synthetic.py). 'truth' is for tests; never show it in the app.",
        "seed": seed,
        "end": end.isoformat(),
        "records": [r.model_dump(mode="json") for r in records],
        "truth": truth,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n")
    return path


def load(path: Path = OUT, end: date | None = None) -> list[DailyRecord]:
    """Maya's records from the saved file, shifted so the last day is `end` (default: today).

    The demo always looks current without regenerating: every date moves by the same amount.
    """
    payload = json.loads(path.read_text())
    records = [DailyRecord.model_validate(r) for r in payload["records"]]
    shift = (end or date.today()) - max(r.date for r in records)
    return [r.model_copy(update={"date": r.date + shift}) for r in records]


def main() -> None:
    parser = argparse.ArgumentParser(description="Write synthetic Maya to data/synthetic/maya.json")
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    print(write(args.end, seed=args.seed))


if __name__ == "__main__":
    main()
