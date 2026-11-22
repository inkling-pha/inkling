"""Raw Fitbit JSON (the data/raw/fitbit/ cache) -> one DailyRecord per day, source="real".

Mapping choices are recorded in docs/data.md ("Mapping to DailyRecord"). In short:
- Every value is dated by the day it belongs to; sleep-derived values by the wake-up day.
- A day with no data for a signal is left out of that signal's dict, so the record field is None,
  never 0.
- Only the type payload is read. The point's `name` (Google account id) is never touched.
"""

import json
import math
import statistics
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from contracts import DailyRecord
from signals.google_health import RAW_DIR

MIN_HRV_SAMPLES = 12  # 5-min samples, so at least 1 hour of the night must have HRV


def _payload(point: dict) -> dict:
    """The type-specific part of a DataPoint, e.g. point["dailyRestingHeartRate"]."""
    return next(v for k, v in point.items() if k not in ("name", "dataSource"))


def _number(value) -> float | None:
    """A float from a number or numeric string. None, "NaN" and inf count as missing."""
    if value is None:
        return None
    x = float(value)
    return x if math.isfinite(x) else None


def _civil_date(d: dict) -> date:
    return date(d["year"], d["month"], d["day"])


def _local_date(utc_time: str, utc_offset: str) -> date:
    """Local calendar day of an RFC-3339 UTC time, given an offset like "-14400s"."""
    seconds = int(utc_offset.removesuffix("s"))
    return (datetime.fromisoformat(utc_time) + timedelta(seconds=seconds)).date()


def _dedupe_key(data_type: str) -> Callable[[dict], object]:
    """What makes two points from overlapping pulls the same point."""
    if data_type == "sleep":
        return lambda p: _payload(p)["interval"]["startTime"]
    if data_type == "steps":
        # Phone and watch can report the same minute separately; keep both.
        return lambda p: (
            _payload(p)["interval"]["startTime"],
            p.get("dataSource", {}).get("application", {}).get("packageName"),
        )
    if data_type == "heart-rate-variability":
        return lambda p: _payload(p)["sampleTime"]["physicalTime"]
    return lambda p: json.dumps(_payload(p)["date"], sort_keys=True)  # daily types


def load_raw(data_type: str, raw_dir: Path = RAW_DIR) -> list[dict]:
    """All cached points of one type. Overlapping pulls are deduped; the newest pull wins."""
    pulls = []
    for path in raw_dir.glob(f"{data_type}_*.json"):
        pull = json.loads(path.read_text())
        if pull.get("data_type") != data_type:
            continue  # e.g. "heart-rate-variability_*" never matches the daily type, but be safe
        if pull.get("source") != "real":
            raise ValueError(f"{path.name}: expected source='real' in the Fitbit cache")
        pulls.append(pull)
    pulls.sort(key=lambda pull: pull.get("pulled_at", ""))
    key = _dedupe_key(data_type)
    points: dict[object, dict] = {}
    for pull in pulls:
        for point in pull["dataPoints"]:
            points[key(point)] = point
    return list(points.values())


def parse_resting_hr(points: list[dict]) -> dict[date, float]:
    """Fitbit's daily resting heart rate (sent as a string), by its own date."""
    out = {}
    for p in map(_payload, points):
        bpm = _number(p.get("beatsPerMinute"))
        if bpm is not None:
            out[_civil_date(p["date"])] = bpm
    return out


def parse_skin_temp(points: list[dict]) -> dict[date, float]:
    """Nightly skin temperature minus Fitbit's personal baseline, by its own (wake-up) date."""
    out = {}
    for p in map(_payload, points):
        nightly = _number(p.get("nightlyTemperatureCelsius"))
        baseline = _number(p.get("baselineTemperatureCelsius"))  # "NaN" before a baseline exists
        if nightly is not None and baseline is not None:
            out[_civil_date(p["date"])] = nightly - baseline
    return out


def _main_sleeps(points: list[dict]) -> dict[date, dict]:
    """The main sleep session per wake-up day (the longest, if several are flagged main)."""
    best: dict[date, dict] = {}
    for s in map(_payload, points):
        if not s.get("metadata", {}).get("mainSleep"):
            continue  # naps and unflagged sessions don't count
        day = _local_date(s["interval"]["endTime"], s["interval"]["endUtcOffset"])
        if day not in best or (_sleep_minutes(s) or 0) > (_sleep_minutes(best[day]) or 0):
            best[day] = s
    return best


class SleepStage(NamedTuple):
    """One stage segment of the main sleep. Signals-internal: not part of the contracts.

    `stage` is the API's stage type (LIGHT, DEEP, REM, AWAKE; classic nights may use others), or
    SHORT_AWAKENING for a brief wake the API lists separately. Short awakenings sit inside
    a sleep stage, so they overlap it in time (mcPHASES' `shortData` works the same way).
    """

    stage: str
    start: datetime  # UTC
    end: datetime  # UTC


SHORT_AWAKENING = "SHORT_AWAKENING"
ASLEEP_STAGES = {"LIGHT", "DEEP", "REM", "ASLEEP"}  # AWAKE, RESTLESS and unknown are not sleep


def _stages(session: dict) -> list[SleepStage]:
    def seg(stage: str, item: dict) -> SleepStage:
        start, end = item["startTime"], item["endTime"]
        return SleepStage(stage, datetime.fromisoformat(start), datetime.fromisoformat(end))

    stages = [seg(st["type"], st) for st in session.get("stages", [])]
    stages += [seg(SHORT_AWAKENING, a) for a in session.get("shortAwakenings", [])]
    return sorted(stages, key=lambda st: (st.start, st.stage == SHORT_AWAKENING))


def _minutes(stage: SleepStage) -> float:
    return (stage.end - stage.start).total_seconds() / 60


def _sleep_minutes(session: dict) -> int | None:
    """Asleep-stage time minus the short awakenings inside it, computed like mcPHASES.

    The API's own summary.minutesAsleep counts short awakenings as sleep (about 20 min a night
    more than mcPHASES; see docs/data.md). Without stage detail we fall back to the summary.
    """
    stages = _stages(session)
    asleep = [st for st in stages if st.stage in ASLEEP_STAGES]
    if not asleep:
        fallback = _number(session.get("summary", {}).get("minutesAsleep"))
        return None if fallback is None else round(fallback)
    short = sum(
        _minutes(a)
        for a in stages
        if a.stage == SHORT_AWAKENING and any(s.start <= a.start and a.end <= s.end for s in asleep)
    )
    return round(sum(map(_minutes, asleep)) - short)


def parse_sleep(points: list[dict]) -> dict[date, int]:
    """Minutes asleep in the main sleep, by wake-up day, short awakenings excluded. No naps."""
    out = {}
    for day, s in _main_sleeps(points).items():
        minutes = _sleep_minutes(s)
        if minutes is not None:
            out[day] = minutes
    return out


def parse_sleep_stages(points: list[dict]) -> dict[date, list[SleepStage]]:
    """Stage segments and short awakenings of the main sleep, by wake-up day, in time order."""
    return {day: st for day, s in _main_sleeps(points).items() if (st := _stages(s))}


def stage_minutes(stages: list[SleepStage]) -> dict[str, float]:
    """Total minutes per stage type, e.g. {"DEEP": 62.0, "REM": 95.5, ...}.

    SHORT_AWAKENING gets its own total; those minutes also sit inside the sleep stages' totals.
    """
    out: dict[str, float] = {}
    for st in stages:
        out[st.stage] = out.get(st.stage, 0.0) + _minutes(st)
    return out


def parse_hrv(hrv_points: list[dict], sleep_points: list[dict]) -> dict[date, float]:
    """Mean of the 5-min RMSSD samples taken during the main sleep, by wake-up day.

    Computed by us rather than taken from Fitbit's daily average, so it matches how mcPHASES HRV
    is computed (see docs/data.md). Nights with fewer than MIN_HRV_SAMPLES samples are left out.
    """
    nights = [
        (
            day,
            datetime.fromisoformat(s["interval"]["startTime"]),
            datetime.fromisoformat(s["interval"]["endTime"]),
        )
        for day, s in _main_sleeps(sleep_points).items()
    ]
    samples: dict[date, list[float]] = {}
    for p in map(_payload, hrv_points):
        rmssd = _number(p.get("rootMeanSquareOfSuccessiveDifferencesMilliseconds"))
        if rmssd is None:
            continue
        t = datetime.fromisoformat(p["sampleTime"]["physicalTime"])
        for day, start, end in nights:
            if start <= t <= end:
                samples.setdefault(day, []).append(rmssd)
                break
    return {day: statistics.mean(v) for day, v in samples.items() if len(v) >= MIN_HRV_SAMPLES}


def parse_steps(points: list[dict]) -> dict[date, int]:
    """Steps per local day, watch and phone together (they don't report the same minutes)."""
    out: dict[date, int] = {}
    for p in map(_payload, points):
        count = _number(p.get("count"))
        if count is None:
            continue
        day = _civil_date(p["interval"]["civilStartTime"]["date"])
        out[day] = out.get(day, 0) + int(count)
    return out


# The Fitbit data types a DailyRecord is built from, and which record fields each one feeds.
# HRV is computed from the samples inside the main sleep, so it needs sleep too.
DATA_TYPES = (
    "daily-resting-heart-rate",
    "daily-sleep-temperature-derivations",
    "heart-rate-variability",
    "sleep",
    "steps",
)
FIELDS_BY_TYPE = {
    "daily-resting-heart-rate": ("rhr_bpm",),
    "daily-sleep-temperature-derivations": ("skin_temp_dev_c",),
    "heart-rate-variability": ("hrv_rmssd_ms",),
    "sleep": ("sleep_min", "hrv_rmssd_ms"),
    "steps": ("steps",),
}


def records_from_points(user_id: str, points: dict[str, list[dict]]) -> list[DailyRecord]:
    """DailyRecords from points keyed by data type. A type that is absent gives None fields."""
    sleep = points.get("sleep", [])
    signals = {
        "rhr_bpm": parse_resting_hr(points.get("daily-resting-heart-rate", [])),
        "hrv_rmssd_ms": parse_hrv(points.get("heart-rate-variability", []), sleep),
        "skin_temp_dev_c": parse_skin_temp(points.get("daily-sleep-temperature-derivations", [])),
        "sleep_min": parse_sleep(sleep),
        "steps": parse_steps(points.get("steps", [])),
    }
    days = sorted(set().union(*signals.values()))
    return [
        DailyRecord(
            user_id=user_id,
            date=day,
            source="real",
            **{field: values.get(day) for field, values in signals.items()},
        )
        for day in days
    ]


def parse_daily_records(user_id: str, raw_dir: Path = RAW_DIR) -> list[DailyRecord]:
    """Every day that has at least one signal in the whole raw cache, oldest first."""
    return records_from_points(user_id, {t: load_raw(t, raw_dir) for t in DATA_TYPES})
