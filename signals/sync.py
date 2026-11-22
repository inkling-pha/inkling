"""Sync Fitbit data into the store: pull recent days, cache raw, parse, save.

- `sync(user_id)` runs on app open (once per session). It pulls from OVERLAP_DAYS before the last
  stored day up to today, because overnight values arrive late and today's steps are partial.
- `backfill(user_id, days)` is the one-time history pull, run by hand, so app load stays fast:
      python -m signals.sync --backfill 90
- If Fitbit can't be reached, nothing stored changes and the status says "cached".
- If one data type fails, the rest are saved, the fields that type feeds keep their stored values,
  and the status says "partial".
- The Fitbit account is the one whose tokens are in .env. Its records are saved under the user id
  you pass; the command line uses LOCAL_USER_ID ("me": whoever's tokens are on this machine).

Statuses and errors never include data values, response bodies or tokens.
"""

import argparse
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import requests

from contracts import DailyRecord
from signals import google_health as gh
from signals import store
from signals.parse import DATA_TYPES, FIELDS_BY_TYPE, parse_sleep_stages, records_from_points

OVERLAP_DAYS = 3  # re-pull the last few stored days: Fitbit fills them in late
MAX_GAP_DAYS = 90  # after a long absence, pull at most this much history on app open
LOCAL_USER_ID = "me"  # the real user on this machine; there is no login, so one id per machine


@dataclass
class SyncStatus:
    """Signals-internal for now. A SyncStatus contract for the app is proposed (D13), not built."""

    mode: Literal["live", "partial", "cached"]  # all types pulled / some failed / none reached
    last_synced_at: datetime | None  # when data last came from Fitbit, None if never
    start: date
    end_exclusive: date
    days_saved: int = 0
    failed_types: list[str] = field(default_factory=list)
    error: str | None = None


def _describe(err: Exception) -> str:
    """A short, safe description of an error: its type and HTTP status, never its body."""
    code = getattr(getattr(err, "response", None), "status_code", None)
    return type(err).__name__ + (f" (HTTP {code})" if code else "")


def _keep_stored_fields(records: list[DailyRecord], failed: list[str]) -> list[DailyRecord]:
    """Fields fed by a failed type keep their stored value instead of becoming None."""
    keep = {f for t in failed for f in FIELDS_BY_TYPE[t]}
    if not keep or not records:
        return records
    user_id, days = records[0].user_id, [r.date for r in records]
    stored = {
        r.date: r
        for r in store.load_daily_records(user_id, min(days), max(days) + timedelta(days=1))
    }
    return [
        r.model_copy(update={f: getattr(stored[r.date], f) for f in keep})
        if r.date in stored
        else r
        for r in records
    ]


def _pull(user_id: str, start: date, end: date) -> SyncStatus:
    """Pull start <= day < end from Fitbit, cache the raw pulls, parse and save.

    API, auth and network errors never raise: they come back as a "cached" or "partial" status.
    """
    now = datetime.now(UTC)
    try:
        gh._access_token()  # fail once here (auth or network), not once per type
    except (requests.RequestException, KeyError, OSError) as err:
        error = _describe(err)
        store.log_sync(user_id, now, "cached", error)
        return SyncStatus("cached", store.last_successful_sync(user_id), start, end, error=error)

    points, failed, errors = {}, [], []
    for data_type in DATA_TYPES:
        # A night's HRV samples start the evening before its wake-up day.
        type_start = start - timedelta(days=1) if data_type == "heart-rate-variability" else start
        try:
            points[data_type] = gh.list_points(data_type, type_start, end)
        except (requests.RequestException, RuntimeError) as err:
            failed.append(data_type)
            errors.append(f"{data_type}: {_describe(err)}")
            continue
        gh.save_raw(data_type, points[data_type], type_start, end)

    mode = "cached" if len(failed) == len(DATA_TYPES) else "partial" if failed else "live"
    records = []
    if mode != "cached":
        records = [r for r in records_from_points(user_id, points) if start <= r.date < end]
        records = _keep_stored_fields(records, failed)
        store.save_daily_records(records)
        if "sleep" in points:
            stages = parse_sleep_stages(points["sleep"])
            store.save_sleep_stages(user_id, {d: s for d, s in stages.items() if start <= d < end})

    error = "; ".join(errors) or None
    store.log_sync(user_id, now, mode, error)
    last = store.last_successful_sync(user_id)
    return SyncStatus(mode, last, start, end, len(records), failed, error)


def sync(user_id: str, today: date | None = None) -> SyncStatus:
    """Pull what's new since the last stored day (plus a few days of overlap) up to today."""
    today = today or date.today()
    last = store.last_record_date(user_id)
    start = max(
        (last or today) - timedelta(days=OVERLAP_DAYS), today - timedelta(days=MAX_GAP_DAYS)
    )
    return _pull(user_id, start, today + timedelta(days=1))


def backfill(user_id: str, days: int, today: date | None = None) -> SyncStatus:
    """One-time history pull of the last `days` days up to today."""
    today = today or date.today()
    return _pull(user_id, today - timedelta(days=days), today + timedelta(days=1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Fitbit data into the Inkling store.")
    parser.add_argument("--user", default=LOCAL_USER_ID, help="user id to save under (default: me)")
    parser.add_argument("--backfill", type=int, metavar="DAYS", help="pull the last DAYS days")
    args = parser.parse_args()
    status = backfill(args.user, args.backfill) if args.backfill else sync(args.user)
    # Counts and type names only: never data values.
    print(
        f"{status.mode}: {status.start} to {status.end_exclusive} (exclusive), "
        f"{status.days_saved} days saved"
        + (f", failed: {', '.join(status.failed_types)}" if status.failed_types else "")
        + (f", error: {status.error}" if status.error else "")
    )


if __name__ == "__main__":
    main()
