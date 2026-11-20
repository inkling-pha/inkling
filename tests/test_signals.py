import json
from datetime import date

import pandas as pd
import pytest
import requests

from contracts import CheckIn, DailyRecord, PhaseEstimate
from signals import google_health as gh
from signals import parse, store
from signals.mcphases import load
from signals.stub import estimate_phase, get_daily_records

START, END = date(2026, 10, 1), date(2026, 10, 3)


def test_stub_matches_contract():
    records = get_daily_records("u1")
    assert records and all(isinstance(r, DailyRecord) and r.user_id == "u1" for r in records)
    assert isinstance(estimate_phase("u1"), PhaseEstimate)


class FakeResponse:
    def __init__(self, body=None, status=200):
        self.body, self.status_code = body or {}, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


@pytest.fixture
def fake_api(monkeypatch, tmp_path):
    """Offline Google Health: no token exchange, pages served from a list, saves go to tmp."""
    monkeypatch.setattr(gh, "_access_token", lambda: "test-token")
    monkeypatch.setattr(gh, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gh, "RAW_DIR", tmp_path / "fitbit")
    calls = []

    def serve(pages):
        def fake_get(url, params, **_):
            calls.append(dict(params))
            return pages.pop(0)

        monkeypatch.setattr(gh.requests, "get", fake_get)
        return calls

    return serve


def test_date_filter_daily_sample_and_unknown():
    assert gh.date_filter("daily-resting-heart-rate", START, END) == (
        'daily_resting_heart_rate.date >= "2026-10-01" AND '
        'daily_resting_heart_rate.date < "2026-10-03"'
    )
    assert gh.date_filter("heart-rate", START, END).startswith("heart_rate.sample_time.civil_time")
    assert gh.date_filter("menstrual-period", START, END) is None


def test_list_points_follows_pages(fake_api):
    calls = fake_api(
        [
            FakeResponse({"dataPoints": [{"a": 1}], "nextPageToken": "p2"}),
            FakeResponse({"dataPoints": [{"a": 2}]}),
        ]
    )
    assert gh.list_points("steps", START, END) == [{"a": 1}, {"a": 2}]
    assert calls[1]["pageToken"] == "p2"


def test_list_points_stops_on_repeated_page_token(fake_api):
    fake_api([FakeResponse({"dataPoints": [], "nextPageToken": "same"})] * 2)
    with pytest.raises(RuntimeError, match="repeated"):
        gh.list_points("steps", START, END)


def test_transient_errors_are_retried(fake_api, monkeypatch):
    monkeypatch.setattr(gh.time, "sleep", lambda _: None)
    ok = FakeResponse({"dataPoints": [{}]})
    fake_api([FakeResponse(status=503), FakeResponse(status=500), ok])
    assert gh.list_points("steps", START, END) == [{}]


def test_persistent_errors_raise_after_retries(fake_api, monkeypatch):
    monkeypatch.setattr(gh.time, "sleep", lambda _: None)
    calls = fake_api([FakeResponse(status=503)] * len(gh.RETRY_WAITS_S))
    with pytest.raises(requests.HTTPError):
        gh.list_points("steps", START, END)
    assert len(calls) == len(gh.RETRY_WAITS_S)


def test_list_points_pulls_long_ranges_in_chunks(fake_api):
    calls = fake_api([FakeResponse({"dataPoints": [{"a": i}]}) for i in range(3)])
    points = gh.list_points("heart-rate", date(2026, 10, 1), date(2026, 10, 16))
    assert len(points) == 3 and len(calls) == 3  # 15 days = 7 + 7 + 1
    assert '>= "2026-10-15"' in calls[2]["filter"]


def test_coverage_counts_days_and_gaps():
    def sample(day, hh, mm):
        return {
            "oxygenSaturation": {
                "sampleTime": {
                    "physicalTime": f"2026-10-{day:02d}T{hh:02d}:{mm:02d}:00Z",
                    "civilTime": {"date": {"year": 2026, "month": 10, "day": day}},
                },
                "percentage": 97,
            }
        }

    daily = {"dailyRestingHeartRate": {"date": {"year": 2026, "month": 10, "day": 2}}}
    cov = gh.coverage([sample(1, 3, 0), sample(1, 3, 1), sample(2, 3, 0)])
    assert cov["days_with_data"] == 2 and cov["median_gap_min"] > 1
    assert gh.coverage([daily])["first_day"] == date(2026, 10, 2)


def test_probe_reports_each_type_and_saves_real(fake_api, tmp_path):
    fake_api(
        [
            FakeResponse({"dataPoints": [{"dailyRestingHeartRate": {"beatsPerMinute": 60}}]}),
            FakeResponse(status=403),
            FakeResponse({"dataPoints": []}),
        ]
    )
    types = ["daily-resting-heart-rate", "daily-sleep-temperature-derivations", "steps"]
    rows = {r["data_type"]: r for r in gh.probe(types, START, END)}
    rhr = rows["daily-resting-heart-rate"]
    assert rhr["fields"] == ["dailyRestingHeartRate.beatsPerMinute"]
    saved = (tmp_path / rhr["saved"]).read_text()
    assert '"source": "real"' in saved
    assert rows["daily-sleep-temperature-derivations"]["status"].startswith("forbidden")
    assert rows["steps"]["status"] == "empty"


def test_mcphases_loader_skips_absent_columns(tmp_path):
    """Synthetic table only: real mcPHASES data never goes in tests."""
    pd.DataFrame({"id": ["a", "b"], "day_in_study": [1, 2], "value": [60.0, 61.0]}).to_csv(
        tmp_path / "resting_heart_rate.csv", index=False
    )
    df = load("resting_heart_rate", ["id", "value", "error"], root=tmp_path)
    assert list(df.columns) == ["id", "value"]


# --- parse: synthetic points shaped like the real Google Health responses -------------------

FAKE_NAME = "users/0000000000/dataTypes/x/dataPoints/y"  # stands in for the Google account id
WATCH = {"recordingMethod": "PASSIVELY_MEASURED", "platform": "FITBIT"}
PHONE = {**WATCH, "application": {"packageName": "com.example.phone"}}


def _date(d: date) -> dict:
    return {"year": d.year, "month": d.month, "day": d.day}


def daily(kind: str, d: date, **fields) -> dict:
    return {"name": FAKE_NAME, "dataSource": WATCH, kind: {"date": _date(d), **fields}}


def sleep_session(
    start, end, minutes, main=True, nap=None, offset="-18000s", stages=(), short=()
) -> dict:
    meta = {"mainSleep": main} if main is not None else {}
    if nap is not None:
        meta["nap"] = nap
    return {
        "name": FAKE_NAME,
        "dataSource": WATCH,
        "sleep": {
            "type": "STAGES",
            "interval": {
                "startTime": start,
                "endTime": end,
                "startUtcOffset": offset,
                "endUtcOffset": offset,
            },
            "metadata": meta,
            "summary": {"minutesAsleep": str(minutes)},
            "stages": [{"type": t, "startTime": a, "endTime": b} for t, a, b in stages],
            "shortAwakenings": [{"startTime": a, "endTime": b} for a, b in short],
        },
    }


def hrv_sample(physical_time: str, rmssd: float) -> dict:
    return {
        "dataSource": WATCH,
        "heartRateVariability": {
            "sampleTime": {"physicalTime": physical_time, "utcOffset": "-18000s"},
            "rootMeanSquareOfSuccessiveDifferencesMilliseconds": rmssd,
        },
    }


def step(d: date, minute: int, count: int, phone: bool = False) -> dict:
    return {
        "dataSource": PHONE if phone else WATCH,
        "steps": {
            "count": str(count),
            "interval": {
                "startTime": f"{d.isoformat()}T15:{minute:02d}:00Z",
                "civilStartTime": {"date": _date(d), "time": {"hours": 10, "minutes": minute}},
            },
        },
    }


def write_pull(raw_dir, data_type, points, pulled_at="2026-10-05T00:00:00+00:00", source="real"):
    raw_dir.mkdir(parents=True, exist_ok=True)
    pull = {"source": source, "data_type": data_type, "pulled_at": pulled_at, "dataPoints": points}
    (raw_dir / f"{data_type}_{pulled_at[:10]}.json").write_text(json.dumps(pull))


D1, D2, D3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)


def test_daily_types_convert_strings_and_skip_incomplete_days():
    rhr = [daily("dailyRestingHeartRate", D1, beatsPerMinute="61")]
    temp = [
        daily(
            "dailySleepTemperatureDerivations",
            D1,
            nightlyTemperatureCelsius=34.1,
            baselineTemperatureCelsius="33.9",
        ),
        daily("dailySleepTemperatureDerivations", D2, nightlyTemperatureCelsius=34.0),
        daily(
            "dailySleepTemperatureDerivations",
            D3,
            nightlyTemperatureCelsius=34.0,
            baselineTemperatureCelsius="NaN",  # sent before a baseline exists
        ),
    ]
    assert parse.parse_resting_hr(rhr) == {D1: 61.0}
    temps = parse.parse_skin_temp(temp)
    assert list(temps) == [D1] and temps[D1] == pytest.approx(0.2)


def test_sleep_counts_main_sleep_only_dated_by_local_wake_day():
    points = [
        # Ends 23:30 UTC on Oct 2, which is 08:30 on Oct 3 at UTC+9: the wake day is Oct 3.
        sleep_session("2026-10-02T15:00:00Z", "2026-10-02T23:30:00Z", 420, offset="+32400s"),
        # A shorter session also flagged main on the same wake day: the longest wins.
        sleep_session(
            "2026-10-03T00:00:00Z", "2026-10-03T01:00:00Z", 50, nap=True, offset="+32400s"
        ),
        # An afternoon nap (not main) is not counted.
        sleep_session(
            "2026-10-03T05:00:00Z",
            "2026-10-03T06:00:00Z",
            55,
            main=None,
            nap=True,
            offset="+32400s",
        ),
    ]
    assert parse.parse_sleep(points) == {D3: 420}


def test_hrv_is_mean_of_main_sleep_samples_and_needs_one_hour():
    sleep = [
        sleep_session("2026-10-01T04:00:00Z", "2026-10-01T12:00:00Z", 450),  # wakes Oct 1
        sleep_session("2026-10-02T04:00:00Z", "2026-10-02T12:00:00Z", 450),  # wakes Oct 2
    ]
    night1 = [hrv_sample(f"2026-10-01T05:{5 * i:02d}:00Z", 30.0 + i) for i in range(12)]
    night2 = [hrv_sample(f"2026-10-02T05:{5 * i:02d}:00Z", 40.0) for i in range(11)]
    awake = [hrv_sample("2026-10-01T18:00:00Z", 99.0)]  # outside any sleep: ignored
    hrv = parse.parse_hrv(night1 + night2 + awake, sleep)
    assert hrv == {D1: pytest.approx(35.5)}  # Oct 2 has only 11 samples, so it is left out


def test_steps_sum_watch_and_phone_per_local_day():
    points = [step(D1, 0, 100), step(D1, 1, 50, phone=True), step(D2, 0, 30, phone=True)]
    assert parse.parse_steps(points) == {D1: 150, D2: 30}


def test_load_raw_newest_pull_wins_and_requires_real(tmp_path):
    raw = tmp_path / "fitbit"
    write_pull(
        raw,
        "daily-resting-heart-rate",
        [daily("dailyRestingHeartRate", D1, beatsPerMinute="60")],
        "2026-10-04T00:00:00Z",
    )
    write_pull(
        raw,
        "daily-resting-heart-rate",
        [daily("dailyRestingHeartRate", D1, beatsPerMinute="62")],
        "2026-10-06T00:00:00Z",
    )
    assert parse.parse_resting_hr(parse.load_raw("daily-resting-heart-rate", raw)) == {D1: 62.0}
    write_pull(raw / "bad", "steps", [], source="synthetic")
    with pytest.raises(ValueError):
        parse.load_raw("steps", raw / "bad")


def test_parse_daily_records_merges_days_and_leaves_gaps_none(tmp_path):
    raw = tmp_path / "fitbit"
    write_pull(
        raw, "daily-resting-heart-rate", [daily("dailyRestingHeartRate", D1, beatsPerMinute="61")]
    )
    write_pull(raw, "steps", [step(D1, 0, 100), step(D2, 0, 0)])
    write_pull(raw, "sleep", [sleep_session("2026-10-01T04:00:00Z", "2026-10-01T12:00:00Z", 400)])
    records = parse.parse_daily_records("maya", raw)
    assert [r.date for r in records] == [D1, D2]
    first, second = records
    assert (first.rhr_bpm, first.sleep_min, first.steps) == (61.0, 400, 100)
    assert first.hrv_rmssd_ms is None and first.skin_temp_dev_c is None
    assert second.steps == 0  # a real zero-step reading stays 0
    assert second.rhr_bpm is None and second.sleep_min is None  # no data is None, never 0
    assert all(r.source == "real" and r.user_id == "maya" for r in records)
    assert "0000000000" not in json.dumps([r.model_dump(mode="json") for r in records])


# --- store -----------------------------------------------------------------------------------


def _record(d: date, **values) -> DailyRecord:
    return DailyRecord(user_id="maya", date=d, source="synthetic", **values)


def test_store_round_trip_keeps_none(tmp_path):
    db = tmp_path / "t.db"
    saved = [_record(D1, rhr_bpm=60.0, steps=5000), _record(D2, hrv_rmssd_ms=42.5)]
    store.save_daily_records(saved, db_path=db)
    assert store.load_daily_records("maya", D1, D3, db_path=db) == saved
    assert store.load_daily_records("someone_else", D1, D3, db_path=db) == []


def test_store_resave_replaces_values_but_keeps_checkins(tmp_path):
    db = tmp_path / "t.db"
    store.save_checkin("maya", D1, CheckIn(bleeding="light", pain=3), db_path=db)
    store.save_daily_records([_record(D1, rhr_bpm=60.0, steps=5000)], db_path=db)
    store.save_daily_records([_record(D1, rhr_bpm=61.0)], db_path=db)
    [day] = store.load_daily_records("maya", D1, D2, db_path=db)
    assert (day.rhr_bpm, day.steps) == (61.0, None)
    assert day.checkin == CheckIn(bleeding="light", pain=3)


def test_checkins_replace_per_day_and_range_is_half_open(tmp_path):
    db = tmp_path / "t.db"
    store.save_checkin("maya", D1, CheckIn(energy=2), db_path=db)
    store.save_checkin("maya", D1, CheckIn(energy=4), db_path=db)
    store.save_checkin("maya", D2, CheckIn(bleeding="none"), source="synthetic", db_path=db)
    assert store.load_checkins("maya", D1, D3, db_path=db) == {
        D1: CheckIn(energy=4),
        D2: CheckIn(bleeding="none"),
    }
    assert list(store.load_checkins("maya", D1, D2, db_path=db)) == [D1]  # end is exclusive
    # A check-in-only day still comes back, with its own source and no wearable values.
    [day] = store.load_daily_records("maya", D2, D3, db_path=db)
    assert day.source == "synthetic" and day.checkin == CheckIn(bleeding="none")
    assert all(getattr(day, f) is None for f in store.WEARABLE_FIELDS)


NIGHT = [  # deliberately out of order: the parser sorts by start time
    ("DEEP", "2026-10-01T05:00:00Z", "2026-10-01T06:00:00Z"),
    ("LIGHT", "2026-10-01T04:00:00Z", "2026-10-01T05:00:00Z"),
    ("AWAKE", "2026-10-01T06:00:00Z", "2026-10-01T06:10:00Z"),
    ("REM", "2026-10-01T06:10:00Z", "2026-10-01T07:40:00Z"),
]


def test_sleep_stages_main_sleep_only_in_time_order():
    points = [
        sleep_session("2026-10-01T04:00:00Z", "2026-10-01T07:40:00Z", 210, stages=NIGHT),
        sleep_session(
            "2026-10-01T18:00:00Z",
            "2026-10-01T19:00:00Z",
            60,
            main=None,
            nap=True,
            stages=[("LIGHT", "2026-10-01T18:00:00Z", "2026-10-01T19:00:00Z")],
        ),
    ]
    stages = parse.parse_sleep_stages(points)
    assert list(stages) == [D1]
    assert [st.stage for st in stages[D1]] == ["LIGHT", "DEEP", "AWAKE", "REM"]
    assert parse.stage_minutes(stages[D1]) == {"LIGHT": 60, "DEEP": 60, "AWAKE": 10, "REM": 90}


def test_sleep_min_subtracts_short_awakenings_like_mcphases():
    short = [
        ("2026-10-01T04:20:00Z", "2026-10-01T04:23:00Z"),  # inside LIGHT: subtracted
        ("2026-10-01T05:30:00Z", "2026-10-01T05:32:00Z"),  # inside DEEP: subtracted
        ("2026-10-01T06:02:00Z", "2026-10-01T06:04:00Z"),  # inside AWAKE: already not sleep
    ]
    # The API summary (210) counts short awakenings as sleep; we don't: 60 + 60 + 90 - 3 - 2.
    night = sleep_session(
        "2026-10-01T04:00:00Z", "2026-10-01T07:40:00Z", 210, stages=NIGHT, short=short
    )
    assert parse.parse_sleep([night]) == {D1: 205}
    stages = parse.parse_sleep_stages([night])[D1]
    assert [st.stage for st in stages].count(parse.SHORT_AWAKENING) == 3
    assert parse.stage_minutes(stages)[parse.SHORT_AWAKENING] == 7
    # Without stage detail, the API summary is the fallback.
    no_stages = sleep_session("2026-10-02T04:00:00Z", "2026-10-02T11:00:00Z", 400)
    assert parse.parse_sleep([no_stages]) == {D2: 400}


def test_store_sleep_stages_round_trip_and_replace(tmp_path):
    db = tmp_path / "t.db"
    night = parse.parse_sleep_stages(
        [
            sleep_session(
                "2026-10-01T04:00:00Z",
                "2026-10-01T07:40:00Z",
                210,
                stages=NIGHT,
                # Starts the same second as the LIGHT stage: both rows must be kept.
                short=[("2026-10-01T04:00:00Z", "2026-10-01T04:02:00Z")],
            )
        ]
    )
    store.save_sleep_stages("maya", night, db_path=db)
    assert store.load_sleep_stages("maya", D1, D2, db_path=db) == night
    shorter = {D1: night[D1][:2]}  # re-parsed night replaces the old segments, no leftovers
    store.save_sleep_stages("maya", shorter, db_path=db)
    assert store.load_sleep_stages("maya", D1, D3, db_path=db) == shorter
    assert store.load_sleep_stages("maya", D2, D3, db_path=db) == {}
