"""SQLite store for parsed DailyRecords and check-ins (stdlib sqlite3, no new dependency).

Sleep stage segments and a log of sync attempts are kept in their own signals-internal tables
(not part of the contracts).

Wearable values and check-ins live in separate tables, so re-parsing Fitbit data never touches
what the user logged. Saving the same (user, day) again replaces it. Missing values are stored as
NULL and come back as None. The DB file lives under data/ (gitignored).
"""

import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from contracts import CheckIn, DailyRecord
from contracts.models import DataSource
from signals.parse import SleepStage

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "inkling.db"
WEARABLE_FIELDS = ("rhr_bpm", "hrv_rmssd_ms", "skin_temp_dev_c", "sleep_min", "steps")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_records (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    rhr_bpm REAL,
    hrv_rmssd_ms REAL,
    skin_temp_dev_c REAL,
    sleep_min INTEGER,
    steps INTEGER,
    source TEXT NOT NULL,
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS checkins (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    checkin TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS sleep_stages (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    stage TEXT NOT NULL,
    start_utc TEXT NOT NULL,
    end_utc TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (user_id, date, start_utc, stage)
);
CREATE TABLE IF NOT EXISTS sync_log (
    user_id TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    error TEXT
);
"""


def _connect() -> sqlite3.Connection:
    # DB_PATH is read at call time, so tests can point it at a temporary file.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def save_daily_records(records: list[DailyRecord]) -> None:
    """Insert or replace the wearable values for each (user, day). Check-ins are not touched."""
    columns = ("user_id", "date", *WEARABLE_FIELDS, "source")
    sql = (
        f"INSERT OR REPLACE INTO daily_records ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})"
    )
    rows = [
        (r.user_id, r.date.isoformat(), *(getattr(r, f) for f in WEARABLE_FIELDS), r.source)
        for r in records
    ]
    with closing(_connect()) as conn, conn:
        conn.executemany(sql, rows)


def save_checkin(
    user_id: str,
    day: date,
    checkin: CheckIn,
    *,
    source: DataSource = "real",
) -> None:
    """Save the day's check-in. A second check-in for the same day replaces the first."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO checkins (user_id, date, checkin, source) VALUES (?, ?, ?, ?)",
            (user_id, day.isoformat(), checkin.model_dump_json(), source),
        )


def _rows(conn, table: str, user_id: str, start: date, end: date) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT * FROM {table} WHERE user_id = ? AND date >= ? AND date < ? ORDER BY date",
        (user_id, start.isoformat(), end.isoformat()),
    ).fetchall()


def load_checkins(user_id: str, start: date, end: date) -> dict[date, CheckIn]:
    """Check-ins with start <= day < end."""
    with closing(_connect()) as conn:
        rows = _rows(conn, "checkins", user_id, start, end)
    return {date.fromisoformat(r["date"]): CheckIn.model_validate_json(r["checkin"]) for r in rows}


def load_daily_records(user_id: str, start: date, end: date) -> list[DailyRecord]:
    """Days with start <= day < end, oldest first, each with that day's check-in attached.

    A day with a check-in but no wearable data is included, with every wearable field None.
    """
    with closing(_connect()) as conn:
        wearable = {r["date"]: r for r in _rows(conn, "daily_records", user_id, start, end)}
        checkins = {r["date"]: r for r in _rows(conn, "checkins", user_id, start, end)}
    records = []
    for day in sorted(wearable.keys() | checkins.keys()):
        w, c = wearable.get(day), checkins.get(day)
        records.append(
            DailyRecord(
                user_id=user_id,
                date=date.fromisoformat(day),
                **({f: w[f] for f in WEARABLE_FIELDS} if w else {}),
                checkin=CheckIn.model_validate_json(c["checkin"]) if c else None,
                source=w["source"] if w else c["source"],
            )
        )
    return records


def save_sleep_stages(
    user_id: str,
    stages_by_day: dict[date, list[SleepStage]],
    *,
    source: DataSource = "real",
) -> None:
    """Replace each given day's stage segments (wake-up day) with the new ones."""
    with closing(_connect()) as conn, conn:
        for day, stages in stages_by_day.items():
            conn.execute(
                "DELETE FROM sleep_stages WHERE user_id = ? AND date = ?",
                (user_id, day.isoformat()),
            )
            conn.executemany(
                "INSERT INTO sleep_stages (user_id, date, stage, start_utc, end_utc, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        user_id,
                        day.isoformat(),
                        st.stage,
                        st.start.isoformat(),
                        st.end.isoformat(),
                        source,
                    )
                    for st in stages
                ],
            )


def load_sleep_stages(user_id: str, start: date, end: date) -> dict[date, list[SleepStage]]:
    """Stage segments by wake-up day, start <= day < end, each day in time order."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM sleep_stages WHERE user_id = ? AND date >= ? AND date < ? "
            "ORDER BY date, start_utc",
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchall()
    out: dict[date, list[SleepStage]] = {}
    for r in rows:
        out.setdefault(date.fromisoformat(r["date"]), []).append(
            SleepStage(
                r["stage"],
                datetime.fromisoformat(r["start_utc"]),
                datetime.fromisoformat(r["end_utc"]),
            )
        )
    return out


def last_record_date(user_id: str) -> date | None:
    """The latest day with stored wearable data for this user, or None if there is none."""
    with closing(_connect()) as conn:
        (day,) = conn.execute(
            "SELECT MAX(date) FROM daily_records WHERE user_id = ?", (user_id,)
        ).fetchone()
    return date.fromisoformat(day) if day else None


def log_sync(user_id: str, synced_at: datetime, mode: str, error: str | None = None) -> None:
    """Record one sync attempt: live, partial or cached."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO sync_log VALUES (?, ?, ?, ?)",
            (user_id, synced_at.isoformat(), mode, error),
        )


def last_successful_sync(user_id: str) -> datetime | None:
    """When data last came from Fitbit (a live or partial sync), or None if it never has."""
    with closing(_connect()) as conn:
        (at,) = conn.execute(
            "SELECT MAX(synced_at) FROM sync_log WHERE user_id = ? AND mode != 'cached'",
            (user_id,),
        ).fetchone()
    return datetime.fromisoformat(at) if at else None
