import json
from datetime import date, timedelta

import pandas as pd
import pytest
import requests

from contracts import CheckIn, DailyRecord, PhaseEstimate
from signals import cycle, parse, store, sync
from signals import google_health as gh
from signals.mcphases import load
from signals.stub import estimate_phase, get_daily_records

START, END = date(2026, 10, 1), date(2026, 10, 3)


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    """Every test gets its own store; tests never touch data/inkling.db."""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "inkling.db")
    return tmp_path / "inkling.db"


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


def test_store_round_trip_keeps_none():
    saved = [_record(D1, rhr_bpm=60.0, steps=5000), _record(D2, hrv_rmssd_ms=42.5)]
    store.save_daily_records(saved)
    assert store.load_daily_records("maya", D1, D3) == saved
    assert store.load_daily_records("someone_else", D1, D3) == []


def test_store_resave_replaces_values_but_keeps_checkins():
    store.save_checkin("maya", D1, CheckIn(bleeding="light", pain=3))
    store.save_daily_records([_record(D1, rhr_bpm=60.0, steps=5000)])
    store.save_daily_records([_record(D1, rhr_bpm=61.0)])
    [day] = store.load_daily_records("maya", D1, D2)
    assert (day.rhr_bpm, day.steps) == (61.0, None)
    assert day.checkin == CheckIn(bleeding="light", pain=3)


def test_checkins_replace_per_day_and_range_is_half_open():
    store.save_checkin("maya", D1, CheckIn(energy=2))
    store.save_checkin("maya", D1, CheckIn(energy=4))
    store.save_checkin("maya", D2, CheckIn(bleeding="none"), source="synthetic")
    assert store.load_checkins("maya", D1, D3) == {
        D1: CheckIn(energy=4),
        D2: CheckIn(bleeding="none"),
    }
    assert list(store.load_checkins("maya", D1, D2)) == [D1]  # end is exclusive
    # A check-in-only day still comes back, with its own source and no wearable values.
    [day] = store.load_daily_records("maya", D2, D3)
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


def test_store_sleep_stages_round_trip_and_replace():
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
    store.save_sleep_stages("maya", night)
    assert store.load_sleep_stages("maya", D1, D2) == night
    shorter = {D1: night[D1][:2]}  # re-parsed night replaces the old segments, no leftovers
    store.save_sleep_stages("maya", shorter)
    assert store.load_sleep_stages("maya", D1, D3) == shorter
    assert store.load_sleep_stages("maya", D2, D3) == {}


def test_get_daily_records_prefers_stored_days_over_the_fixture():
    assert all(r.source == "synthetic" for r in get_daily_records("new-user"))  # fixture
    stored = [DailyRecord(user_id="me", date=D1, rhr_bpm=60.0, source="real")]
    store.save_daily_records(stored)
    assert get_daily_records("me") == stored


# --- sync: fake Fitbit, no network ----------------------------------------------------------

TODAY = date(2026, 10, 10)


@pytest.fixture
def fake_fitbit(monkeypatch, tmp_path):
    """Serve fixed points per type; types in `failing` raise like a 503. Records every pull."""
    monkeypatch.setattr(gh, "RAW_DIR", tmp_path / "fitbit")
    state = {"points": {}, "failing": set(), "auth_fails": False, "calls": []}

    def token():
        if state["auth_fails"]:
            raise requests.HTTPError(response=FakeResponse(status=401))
        return "test-token"

    def list_points(data_type, start, end):
        state["calls"].append((data_type, start, end))
        if data_type in state["failing"]:
            raise requests.HTTPError(response=FakeResponse(status=503))
        return state["points"].get(data_type, [])

    monkeypatch.setattr(gh, "_access_token", token)
    monkeypatch.setattr(gh, "list_points", list_points)
    return state


def _night(wake: date, short=()):
    """A main sleep ending 07:00 local (UTC-5) on `wake`, with 12 HRV samples and stages."""
    w = wake.isoformat()
    stages = [
        ("LIGHT", f"{w}T04:00:00Z", f"{w}T08:00:00Z"),
        ("DEEP", f"{w}T08:00:00Z", f"{w}T12:00:00Z"),
    ]
    session = sleep_session(f"{w}T04:00:00Z", f"{w}T12:00:00Z", 480, stages=stages, short=short)
    samples = [hrv_sample(f"{w}T05:{5 * i:02d}:00Z", 40.0) for i in range(12)]
    return session, samples


def test_first_sync_pulls_recent_days_saves_and_logs(fake_fitbit):
    session, samples = _night(TODAY)
    fake_fitbit["points"] = {
        "daily-resting-heart-rate": [daily("dailyRestingHeartRate", TODAY, beatsPerMinute="60")],
        "sleep": [session],
        "heart-rate-variability": samples,
        "steps": [step(TODAY, 0, 500), step(date(2026, 9, 1), 0, 9)],  # outside the window: dropped
    }
    status = sync.sync("me", TODAY)
    assert status.mode == "live" and status.failed_types == [] and status.error is None
    assert (status.start, status.end_exclusive) == (date(2026, 10, 7), date(2026, 10, 11))
    hrv_call = next(c for c in fake_fitbit["calls"] if c[0] == "heart-rate-variability")
    assert hrv_call[1] == date(2026, 10, 6)  # one extra day: samples start the evening before
    [day] = store.load_daily_records("me", date(2026, 1, 1), date(2027, 1, 1))
    assert (day.date, day.rhr_bpm, day.sleep_min, day.steps, day.hrv_rmssd_ms) == (
        TODAY,
        60.0,
        480,
        500,
        40.0,
    )
    assert day.skin_temp_dev_c is None and day.source == "real"
    assert list(store.load_sleep_stages("me", TODAY, date(2026, 10, 11))) == [TODAY]
    assert status.last_synced_at is not None
    assert len(list(gh.RAW_DIR.glob("*.json"))) == len(parse.DATA_TYPES)  # raw pulls cached


def test_next_sync_starts_three_days_before_last_stored_day_and_caps_long_gaps(fake_fitbit):
    store.save_daily_records(
        [DailyRecord(user_id="me", date=date(2026, 10, 8), steps=1, source="real")]
    )
    assert sync.sync("me", TODAY).start == date(2026, 10, 5)
    store.save_daily_records(
        [DailyRecord(user_id="u2", date=date(2025, 1, 1), steps=1, source="real")]
    )
    assert sync.sync("u2", TODAY).start == TODAY - timedelta(days=sync.MAX_GAP_DAYS)


def test_failed_auth_keeps_stored_data_and_reports_cached(fake_fitbit):
    fake_fitbit["points"] = {"steps": [step(TODAY, 0, 500)]}
    sync.sync("me", TODAY)
    fake_fitbit["auth_fails"] = True
    status = sync.sync("me", TODAY)
    assert status.mode == "cached" and status.error == "HTTPError (HTTP 401)"
    assert status.last_synced_at is not None  # from the earlier live sync
    assert get_daily_records("me")[0].steps == 500


def test_one_failed_type_keeps_its_stored_values(fake_fitbit):
    fake_fitbit["points"] = {
        "daily-resting-heart-rate": [daily("dailyRestingHeartRate", TODAY, beatsPerMinute="60")],
        "steps": [step(TODAY, 0, 500)],
    }
    sync.sync("me", TODAY)
    fake_fitbit["points"]["steps"] = [step(TODAY, 0, 800)]
    fake_fitbit["failing"] = {"daily-resting-heart-rate"}
    status = sync.sync("me", TODAY)
    assert status.mode == "partial" and status.failed_types == ["daily-resting-heart-rate"]
    assert "HTTP 503" in status.error
    [day] = store.load_daily_records("me", TODAY, date(2026, 10, 11))
    assert (day.rhr_bpm, day.steps) == (60.0, 800)  # RHR kept, steps updated


# --- cycle: period starts and the calendar estimate (synthetic check-ins) ---

NOV_1 = date(2026, 11, 1)


def log_bleeding(user_id: str, first: date, levels: list[str | None]) -> None:
    """One check-in per day from `first`, with these bleeding answers."""
    for i, level in enumerate(levels):
        store.save_checkin(user_id, first + timedelta(days=i), CheckIn(bleeding=level))


def test_spotting_alone_never_starts_a_period_and_mid_cycle_flow_is_not_a_new_one():
    log_bleeding("u1", date(2026, 9, 1), ["spot", "light", "heavy", "medium", "light", "spot"])
    log_bleeding("u1", date(2026, 9, 14), ["spot", "spot"])  # mid-cycle spotting
    log_bleeding("u1", date(2026, 9, 10), ["light"])  # within MIN_GAP_DAYS of the last flow
    log_bleeding("u1", date(2026, 10, 1), ["light", "medium", None, "spot"])  # one skipped day
    assert cycle.periods("u1", NOV_1) == [
        (date(2026, 9, 2), date(2026, 9, 6)),
        (date(2026, 10, 1), date(2026, 10, 4)),
    ]
    assert cycle.cycle_lengths("u1", NOV_1) == [29]


def test_no_period_logged_means_unknown_not_a_guess():
    # Fitbit data, no check-ins.
    store.save_daily_records([DailyRecord(user_id="u1", date=NOV_1, rhr_bpm=60.0, source="real")])
    est = estimate_phase("u1")
    assert (est.phase, est.cycle_day, est.confidence, est.source) == ("unknown", None, 0.0, "real")
    assert cycle.days_since_last_period("u1", NOV_1) is None


def test_stub_uses_the_fixture_only_when_nothing_is_stored():
    assert estimate_phase("u1").source == "synthetic"
    store.save_checkin("u1", NOV_1, CheckIn(bleeding="none"))
    assert estimate_phase("u1").method == "calendar"


@pytest.mark.parametrize(
    ("day", "phase"),
    [
        (1, "menstrual"),
        (6, "menstrual"),
        (7, "follicular"),
        (15, "follicular"),
        (16, "ovulatory"),
        (18, "ovulatory"),
        (19, "luteal"),
        (36, "luteal"),
        (37, "unknown"),
    ],
)
def test_one_period_counts_from_the_default_29_day_cycle(day, phase):
    log_bleeding("u1", date(2026, 9, 1), ["heavy", "medium", "light"])
    est = cycle.estimate_phase("u1", date(2026, 9, 1) + timedelta(days=day - 1))
    assert (est.phase, est.cycle_day) == (phase, day)
    assert est.confidence == (0.0 if phase == "unknown" else cycle.CALENDAR_CONFIDENCE)
    assert est.ovulation_est_date is None and est.ovulation_window is None  # D25


def test_her_own_cycles_set_the_usual_length_capped_at_38_days():
    for start in (date(2026, 6, 1), date(2026, 7, 6), date(2026, 8, 10)):  # 35-day cycles
        log_bleeding("u1", start, ["medium", "medium", "light", "light"])
    start = date(2026, 8, 10)
    assert cycle.estimate_phase("u1", start + timedelta(days=22)).phase == "ovulatory"  # 35 - 12
    assert cycle.estimate_phase("u1", start + timedelta(days=37)).phase == "luteal"  # day 38
    assert cycle.estimate_phase("u1", start + timedelta(days=38)).phase == "unknown"  # day 39


def test_still_bleeding_past_the_usual_length_is_menstrual():
    log_bleeding("u1", date(2026, 10, 1), ["heavy"] * 7)
    assert cycle.estimate_phase("u1", date(2026, 10, 7)).phase == "menstrual"


def test_days_since_last_period_is_none_when_she_stopped_answering():
    log_bleeding("u1", date(2026, 7, 1), ["heavy", "medium"])
    log_bleeding("u1", date(2026, 10, 1), ["none"] + [None] * 30)  # checked in, skipped bleeding
    assert cycle.days_since_last_period("u1", date(2026, 10, 10)) == 101
    assert cycle.days_since_last_period("u1", date(2026, 10, 16)) is None


def test_recent_birth_control_makes_the_phase_unknown_but_keeps_period_tracking():
    log_bleeding("u1", date(2026, 9, 1), ["heavy", "medium", "light"])
    store.save_checkin("u1", date(2026, 9, 5), CheckIn(bleeding="none", bc_taken=True))
    est = cycle.estimate_phase("u1", date(2026, 9, 10))
    assert (est.phase, est.cycle_day, est.confidence) == ("unknown", None, 0.0)
    assert cycle.days_since_last_period("u1", date(2026, 9, 10)) == 9
    # Over BC_LOOKBACK_DAYS after the last bc_taken, the calendar count applies again.
    log_bleeding("u1", date(2026, 10, 1), ["heavy", "medium"])
    assert cycle.estimate_phase("u1", date(2026, 10, 15)).phase == "follicular"


# --- mcPHASES records: synthetic tables shaped like the real files (never real data) ---------

from signals import mcphases_records as mr  # noqa: E402


def _write(root, name, rows):
    pd.DataFrame(rows).to_csv(root / f"{name}.csv", index=False)


def _synthetic_mcphases(root):
    """Two people; zz-a has 2022 and 2024 rounds, zz-b only 2022. Includes the documented quirks."""
    hormones = [
        {"id": "zz-a", "study_interval": 2022, "day_in_study": 1, "phase": "Menstrual",
         "flow_volume": "Heavy"},
        {"id": "zz-a", "study_interval": 2022, "day_in_study": 2, "phase": "Fertility",
         "flow_volume": None},
        {"id": "zz-b", "study_interval": 2022, "day_in_study": 1, "phase": "Luteal",
         "flow_volume": "Not at all"},
        {"id": "zz-a", "study_interval": 2024, "day_in_study": 850, "phase": "Follicular",
         "flow_volume": "Spotting / Very Light"},
    ]  # fmt: skip
    _write(root, "hormones_and_selfreport", hormones)
    temp = [  # zz-a night into day 2: two sessions -> median; an exact 0 deviation is missing
        {"id": "zz-a", "study_interval": 2022, "sleep_start_day_in_study": 1,
         "sleep_end_day_in_study": 2, "sleep_start_timestamp": "23:00:00",
         "baseline_relative_sample_sum": 30.0, "temperature_samples": 100},
        {"id": "zz-a", "study_interval": 2022, "sleep_start_day_in_study": 2,
         "sleep_end_day_in_study": 2, "sleep_start_timestamp": "14:00:00",
         "baseline_relative_sample_sum": 10.0, "temperature_samples": 100},
        {"id": "zz-b", "study_interval": 2022, "sleep_start_day_in_study": 0,
         "sleep_end_day_in_study": 1, "sleep_start_timestamp": "23:00:00",
         "baseline_relative_sample_sum": 0.0, "temperature_samples": 100},
    ]  # fmt: skip
    _write(root, "computed_temperature", temp + temp[:1])  # an exact duplicate row
    hrv = []
    for i in range(6):  # 6 evening samples on day 1 + 6 morning samples on day 2 -> night of day 2
        hrv.append(
            {
                "id": "zz-a",
                "study_interval": 2022,
                "day_in_study": 1,
                "timestamp": f"23:{i * 5:02d}:00",
                "rmssd": 40.0,
                "coverage": 0.9,
            }
        )
        hrv.append(
            {
                "id": "zz-a",
                "study_interval": 2022,
                "day_in_study": 2,
                "timestamp": f"03:{i * 5:02d}:00",
                "rmssd": 50.0,
                "coverage": 0.9,
            }
        )
    hrv.append({"id": "zz-b", "study_interval": 2022, "day_in_study": 1,  # too few samples
                "timestamp": "02:00:00", "rmssd": 60.0, "coverage": 0.9})  # fmt: skip
    _write(root, "heart_rate_variability_details", hrv + hrv[:2])
    sleeps = [  # duplicate session copies (keep the longer), plus a nap that is not main sleep
        {"id": "zz-a", "study_interval": 2022, "sleep_start_day_in_study": 1,
         "sleep_end_day_in_study": 2, "sleep_start_timestamp": "23:00:00",
         "minutesasleep": 400, "mainsleep": True},
        {"id": "zz-a", "study_interval": 2022, "sleep_start_day_in_study": 1,
         "sleep_end_day_in_study": 2, "sleep_start_timestamp": "23:00:00",
         "minutesasleep": 410, "mainsleep": True},
        {"id": "zz-a", "study_interval": 2022, "sleep_start_day_in_study": 2,
         "sleep_end_day_in_study": 2, "sleep_start_timestamp": "14:00:00",
         "minutesasleep": 60, "mainsleep": False},
    ]  # fmt: skip
    _write(root, "sleep", sleeps)
    rhr = [
        {"id": "zz-a", "study_interval": 2022, "day_in_study": 1, "value": 62.0, "error": 0},
        {"id": "zz-b", "study_interval": 2022, "day_in_study": 1, "value": 0.0, "error": 100},
        {"id": "zz-a", "study_interval": 2024, "day_in_study": 850, "value": 70.0, "error": 0},
        {"id": "zz-a", "study_interval": 2024, "day_in_study": 850, "value": 88.0, "error": 0},
    ]
    _write(root, "resting_heart_rate", rhr)
    steps = [
        {"id": "zz-a", "study_interval": 2022, "day_in_study": 1, "timestamp": "10:00:00",
         "steps": 30},
        {"id": "zz-a", "study_interval": 2022, "day_in_study": 1, "timestamp": "10:01:00",
         "steps": 12},
        {"id": "zz-a", "study_interval": 2024, "day_in_study": 850, "timestamp": "10:00:00",
         "steps": 999},
    ]  # fmt: skip
    _write(root, "steps", steps)


def _row(frame, user_id, day):
    return frame[(frame.user_id == user_id) & (frame.day_in_study == day)].iloc[0]


def test_mcphases_frame_applies_cleaning_rules(tmp_path):
    _synthetic_mcphases(tmp_path)
    frame = mr.build_frame(tmp_path)
    assert len(frame) == 4 and not frame.duplicated(subset=mr.KEY).any()
    d1, d2 = _row(frame, "mcphases-zz-a-2022", 1), _row(frame, "mcphases-zz-a-2022", 2)
    assert d1.rhr_bpm == 62.0 and d1.steps == 42
    assert d2.skin_temp_dev_c == pytest.approx(0.2)  # median of 0.3 and 0.1
    assert d2.hrv_rmssd_ms == pytest.approx(45.0)  # evening + morning samples, one night
    assert d2.sleep_min == 410  # longer copy, nap ignored
    p2 = _row(frame, "mcphases-zz-b-2022", 1)
    assert pd.isna(p2.rhr_bpm) and pd.isna(p2.skin_temp_dev_c) and pd.isna(p2.hrv_rmssd_ms)
    r24 = _row(frame, "mcphases-zz-a-2024", 850)
    assert pd.isna(r24.rhr_bpm) and pd.isna(r24.steps)  # 2024 RHR and steps are left out


def test_mcphases_records_and_labels(tmp_path):
    _synthetic_mcphases(tmp_path)
    frame = mr.build_frame(tmp_path)
    records = mr.to_records(frame)
    assert all(isinstance(r, DailyRecord) and r.source == "real" for r in records)
    first = next(r for r in records if r.user_id == "mcphases-zz-a-2022" and r.date == mr.EPOCH
                 + pd.Timedelta(days=1))  # fmt: skip
    assert first.checkin.bleeding == "heavy" and first.checkin.pain is None
    no_diary = next(r for r in records if r.user_id == "mcphases-zz-a-2022" and r.checkin is None)
    assert no_diary.rhr_bpm is None  # missing stays None, never 0
    labels = mr.phase_labels(frame)
    assert sorted(set(labels.values())) == ["follicular", "luteal", "menstrual", "ovulatory"]


def test_mcphases_summary_is_aggregates_only(tmp_path):
    _synthetic_mcphases(tmp_path)
    out = mr.summary(mr.build_frame(tmp_path), root=tmp_path)
    assert out["rounds"]["2022"]["participants"] == 2
    assert out["hrv_dating_check"]["shift_at_12h"] == 1.0
    text = json.dumps(out, default=str)
    assert "zz-a" not in text and "zz-b" not in text  # no participant ids in the output


def test_mcphases_schema_report_flags_missing_columns(tmp_path):
    _synthetic_mcphases(tmp_path)
    (tmp_path / "steps.csv").unlink()
    report = mr.schema_report(tmp_path)
    assert report["steps"] == "file missing"
    assert report["sleep"]["missing"] == []


# --- detector: synthetic cycles with a clean luteal rise ------------------------------------


from signals import detector  # noqa: E402

DAY0 = date(2026, 1, 1)
LUTEAL_FROM = 15  # cycle days 15-28 are luteal in these synthetic 28-day cycles


def _cycles(n_cycles=3, temp=True, rhr=True, hrv=True, skip=()):
    records = []
    for i in range(28 * n_cycles):
        luteal = i % 28 + 1 >= LUTEAL_FROM
        if i in skip:
            continue
        records.append(
            DailyRecord(
                user_id="synthetic",
                date=DAY0 + timedelta(days=i),
                skin_temp_dev_c=(0.15 if luteal else -0.1) if temp else None,
                rhr_bpm=(66.0 if luteal else 63.5) if rhr else None,
                hrv_rmssd_ms=(42.0 if luteal else 48.0) if hrv else None,
                source="synthetic",
            )
        )
    return records


def _is_luteal(d):
    return (d - DAY0).days % 28 + 1 >= LUTEAL_FROM


def test_detector_finds_the_luteal_rise_after_warm_up():
    states = detector.detect(_cycles())
    warm = [s for s in states if (s.date - DAY0).days >= 28]  # after one cycle of baseline
    decided = [s for s in warm if s.luteal_like is not None]
    correct = sum(s.luteal_like == _is_luteal(s.date) for s in decided)
    assert len(decided) / len(warm) > 0.8
    assert correct / len(decided) > 0.85
    mid_luteal = next(s for s in warm if (s.date - DAY0).days % 28 + 1 == 20)
    assert mid_luteal.luteal_like is True and mid_luteal.votes == {
        "skin_temp_dev_c": 1,
        "rhr_bpm": 1,
        "hrv_rmssd_ms": 1,
    }


def test_detector_says_not_enough_data_at_the_start():
    states = detector.detect(_cycles())
    assert all(s.luteal_like is None for s in states[: detector.MIN_BASELINE_NIGHTS])


def test_detector_uses_whatever_signals_exist():
    states = detector.detect(_cycles(rhr=False, hrv=False))  # temperature only
    s = next(s for s in states if (s.date - DAY0).days == 28 + 19)
    assert set(s.votes) == {"skin_temp_dev_c"} and s.luteal_like is True


def test_detector_abstains_without_signal_and_never_looks_ahead():
    empty = detector.detect(_cycles(temp=False, rhr=False, hrv=False))
    assert all(s.luteal_like is None and not s.votes for s in empty)
    full = _cycles()
    cut = DAY0 + timedelta(days=40)
    past_only = [r for r in full if r.date <= cut]
    a = {s.date: s for s in detector.detect(full)}
    b = {s.date: s for s in detector.detect(past_only)}
    assert all(a[d] == b[d] for d in b)  # adding future nights changes no past verdict


def test_detector_tolerates_missing_nights():
    states = detector.detect(_cycles(skip=set(range(50, 60))))
    assert len(states) == 28 * 3 - 10


# --- signals eval: scoring helpers and an end-to-end run on synthetic tables ----------------

from evals.signals import run as signals_eval  # noqa: E402


def test_eval_scores_and_lag():
    d = [DAY0 + timedelta(days=i) for i in range(6)]
    labels = {("u", d[i]): p for i, p in enumerate(["follicular"] * 2 + ["luteal"] * 4)}
    preds = {("u", d[0]): False, ("u", d[1]): None, ("u", d[2]): False, ("u", d[3]): True,
             ("u", d[4]): True, ("u", d[5]): True}  # fmt: skip
    s = signals_eval.score(preds, labels)
    assert s["coverage"] == round(5 / 6, 3)
    assert s["sensitivity"] == 0.75 and s["specificity"] == 1.0
    lag = signals_eval.detection_lag(preds, labels)
    assert lag["luteal_runs"] == 1 and lag["median_lag_days"] == 1


def test_eval_split_is_fixed_and_by_person():
    ids = [f"person-{i}" for i in range(200)]
    test = [i for i in ids if signals_eval.is_test(i)]
    assert test == [i for i in ids if signals_eval.is_test(i)]
    assert 0.15 < len(test) / len(ids) < 0.45


def test_eval_runs_end_to_end_and_prints_no_ids(tmp_path, monkeypatch, capsys):
    _synthetic_mcphases(tmp_path)
    build = mr.build_frame
    monkeypatch.setattr(mr, "build_frame", lambda: build(tmp_path))
    result = signals_eval.main()
    assert set(result) >= {"people", "best_params", "train", "test", "test_detection_lag"}
    out = capsys.readouterr().out
    assert "zz-a" not in out and "zz-b" not in out


def test_eval_bootstrap_intervals_resample_people():
    same = {"all": [8, 2, 8, 2, 0], "temp_only": [6, 4, 6, 4, 0]}
    per_person = {f"person-{i}": same for i in range(6)}
    out = signals_eval.bootstrap(per_person, n=200)
    assert out["balanced_accuracy_95ci"]["all"] == [0.8, 0.8]  # identical people: no spread
    assert out["all_minus_set_balanced_accuracy_95ci"]["temp_only"] == [0.2, 0.2]
    mixed = {"good": {"all": [9, 1, 9, 1, 0]}, "poor": {"all": [5, 5, 5, 5, 0]}}
    low, high = signals_eval.bootstrap(mixed, n=500)["balanced_accuracy_95ci"]["all"]
    assert low == 0.5 and high == 0.9  # a resample can draw the same person twice
