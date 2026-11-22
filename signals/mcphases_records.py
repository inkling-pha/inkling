"""mcPHASES -> one cleaned row per (participant, round, day), then DailyRecords + phase labels.

Applies the cleaning recipe in docs/data.md ("Cleaning" -> "One value per day"). Used offline by the
phase model and the held-out signals eval (D15). Never by the app, and never sent to an LLM (D18).

Run it yourself (Claude can't, by design); both modes print aggregates only, never rows:

    python -m signals.mcphases_records --schema   # expected vs actual column names per table
    python -m signals.mcphases_records            # counts, % missing, percentiles, checks

Choices that aren't in docs/data.md yet (the summary reports the numbers behind each):
- **user_id** is "mcphases-<id>-<round>", so the 2022 and 2024 rounds are separate sequences and
  never bridged.
- **date:** mcPHASES has no calendar dates, so `date = EPOCH + day_in_study days`. Not a real date;
  only the differences between dates mean anything.
- **HRV night:** 5-min samples carry the day and time of day. HRV_EVENING_HOUR decides which samples
  belong to the next morning's wake day. The summary shows how well each rule lines up with sleep.
- **checkin:** only `bleeding` (the flow_volume mapping in docs/data.md). `pain` stays None until
  D25 settles how 6 text levels map to 0-10.
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from contracts import CheckIn, DailyRecord
from signals.mcphases import data_dir, load

EPOCH = date(2000, 1, 1)  # placeholder calendar for day_in_study; never shown as a real date
HRV_EVENING_HOUR = 12  # samples at or after this hour count toward the next day's night
MIN_HRV_SAMPLES = 12  # same as signals/parse.py: at least 1 hour of 5-min samples
RHR_STEPS_ROUNDS = {2022}  # 2024 copies disagree (docs/data.md, "Why 2024 RHR and steps ...")

KEY = ["id", "study_interval", "day_in_study"]
SIGNALS = ["rhr_bpm", "hrv_rmssd_ms", "skin_temp_dev_c", "sleep_min", "steps"]

# Columns each table needs, from docs/data.md. `--schema` checks them against the files.
COLUMNS = {
    "hormones_and_selfreport": ["id", "study_interval", "day_in_study", "phase", "flow_volume"],
    "computed_temperature": [
        "id",
        "study_interval",
        "sleep_start_day_in_study",
        "sleep_end_day_in_study",
        "sleep_start_timestamp",
        "baseline_relative_sample_sum",
        "temperature_samples",
    ],
    "heart_rate_variability_details": [
        "id",
        "study_interval",
        "day_in_study",
        "timestamp",
        "rmssd",
        "coverage",
    ],
    "sleep": [
        "id",
        "study_interval",
        "sleep_start_day_in_study",
        "sleep_end_day_in_study",
        "sleep_start_timestamp",
        "minutesasleep",
        "mainsleep",
    ],
    "resting_heart_rate": ["id", "study_interval", "day_in_study", "value", "error"],
    "steps": ["id", "study_interval", "day_in_study", "timestamp", "steps"],
}

PHASES = {
    "Menstrual": "menstrual",
    "Follicular": "follicular",
    "Fertility": "ovulatory",  # a fertile window, not ovulation day (docs/data.md, D25)
    "Luteal": "luteal",
}
BLEEDING = {
    "Not at all": "none",
    "Spotting / Very Light": "spot",
    "Light": "light",
    "Somewhat Light": "light",
    "Moderate": "medium",
    "Somewhat Heavy": "heavy",
    "Heavy": "heavy",
    "Very Heavy": "heavy",
}


# --- per-table cleaning: each returns one row per KEY ------------------------------------------


def _round(df: pd.DataFrame) -> pd.DataFrame:
    df["study_interval"] = pd.to_numeric(df["study_interval"], errors="coerce").astype("Int64")
    return df


def _hour(timestamp: pd.Series) -> pd.Series:
    """Hour from a time-of-day string like '23:45:00'."""
    return pd.to_numeric(timestamp.astype(str).str.slice(0, 2), errors="coerce")


def _truthy(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin({"true", "1", "1.0", "yes"})


def labels_and_bleeding(t: pd.DataFrame) -> pd.DataFrame:
    t = _round(t)
    out = t[KEY].copy()
    out["phase"] = t["phase"].map(PHASES)  # anything unmapped becomes NaN, counted in the summary
    out["bleeding"] = t["flow_volume"].map(BLEEDING)
    return out


def skin_temp(t: pd.DataFrame) -> pd.DataFrame:
    """Mean nightly deviation (sum / samples), median per wake day. Exact 0 means no baseline."""
    t = _round(t).drop_duplicates()
    samples = pd.to_numeric(t["temperature_samples"], errors="coerce")
    dev = pd.to_numeric(t["baseline_relative_sample_sum"], errors="coerce") / samples.where(
        samples > 0
    )
    t = t.assign(day_in_study=t["sleep_end_day_in_study"], skin_temp_dev_c=dev.where(dev != 0))
    return t.groupby(KEY, as_index=False)["skin_temp_dev_c"].median()


def _hrv_nights(t: pd.DataFrame, evening_hour: int | None) -> pd.DataFrame:
    """Mean RMSSD and sample count per (id, round, night), before the 12-sample minimum."""
    rmssd = pd.to_numeric(t["rmssd"], errors="coerce")
    day = t["day_in_study"]
    if evening_hour is not None:
        day = day + (_hour(t["timestamp"]) >= evening_hour).astype(int)
    t = t.assign(day_in_study=day, rmssd=rmssd.where(rmssd > 0)).dropna(subset=["rmssd"])
    return t.groupby(KEY)["rmssd"].agg(["mean", "size"]).reset_index()


def hrv(t: pd.DataFrame, evening_hour: int | None = HRV_EVENING_HOUR) -> pd.DataFrame:
    """Mean of the 5-min RMSSD samples per night, dated by wake day; 12+ samples needed.

    evening_hour=None keeps day_in_study as is (the alternative the summary compares against).
    """
    t = _round(t).drop_duplicates(subset=["id", "study_interval", "day_in_study", "timestamp"])
    nights = _hrv_nights(t, evening_hour)
    nights = nights[nights["size"] >= MIN_HRV_SAMPLES]
    return nights.rename(columns={"mean": "hrv_rmssd_ms"})[KEY + ["hrv_rmssd_ms"]]


def sleep(t: pd.DataFrame) -> pd.DataFrame:
    """Longer copy per session, then the main sleep per wake day (the longest if several)."""
    t = _round(t)
    t = t.assign(minutesasleep=pd.to_numeric(t["minutesasleep"], errors="coerce"))
    session = ["id", "study_interval", "sleep_start_day_in_study", "sleep_start_timestamp"]
    t = t.sort_values("minutesasleep").drop_duplicates(subset=session, keep="last")
    t = t[_truthy(t["mainsleep"])].assign(day_in_study=t["sleep_end_day_in_study"])
    t = t.sort_values("minutesasleep").drop_duplicates(subset=KEY, keep="last")
    return t.rename(columns={"minutesasleep": "sleep_min"})[KEY + ["sleep_min"]]


def resting_hr(t: pd.DataFrame) -> pd.DataFrame:
    """2022 only; 0 is a sentinel for missing."""
    t = _round(t)
    t = t[t["study_interval"].isin(RHR_STEPS_ROUNDS)]
    value = pd.to_numeric(t["value"], errors="coerce")
    t = t.assign(rhr_bpm=value.where(value > 0)).dropna(subset=["rhr_bpm"])
    return t.groupby(KEY, as_index=False)["rhr_bpm"].median()  # 2022 has one per day


def daily_steps(t: pd.DataFrame) -> pd.DataFrame:
    """2022 only; per-minute counts summed per day."""
    t = _round(t)
    t = t[t["study_interval"].isin(RHR_STEPS_ROUNDS)].drop_duplicates(
        subset=["id", "study_interval", "day_in_study", "timestamp"]
    )
    t = t.assign(steps=pd.to_numeric(t["steps"], errors="coerce"))
    return t.groupby(KEY, as_index=False)["steps"].sum(min_count=1)


# --- assembly ----------------------------------------------------------------------------------


def _assert_unique(df: pd.DataFrame, name: str) -> None:
    dupes = int(df.duplicated(subset=KEY).sum())
    if dupes:
        raise ValueError(f"{name}: {dupes} duplicate (id, round, day) rows after cleaning")


def build_frame(root: Path | None = None) -> pd.DataFrame:
    """One row per (id, round, day) with a hormone-table row: labels, bleeding and the signals."""
    tables = {name: load(name, cols, root=root) for name, cols in COLUMNS.items()}
    base = labels_and_bleeding(tables["hormones_and_selfreport"])
    parts = {
        "computed_temperature": skin_temp(tables["computed_temperature"]),
        "heart_rate_variability_details": hrv(tables["heart_rate_variability_details"]),
        "sleep": sleep(tables["sleep"]),
        "resting_heart_rate": resting_hr(tables["resting_heart_rate"]),
        "steps": daily_steps(tables["steps"]),
    }
    _assert_unique(base, "hormones_and_selfreport")
    frame = base
    for name, part in parts.items():
        _assert_unique(part, name)
        frame = frame.merge(part, on=KEY, how="left")  # left: days come from the hormone table
    _assert_unique(frame, "merged frame")
    if len(frame) != len(base):
        raise ValueError("merge changed the row count")
    frame["user_id"] = (
        "mcphases-" + frame["id"].astype(str) + "-" + frame["study_interval"].astype(str)
    )
    frame["date"] = [EPOCH + timedelta(days=int(d)) for d in frame["day_in_study"]]
    return frame.sort_values(["user_id", "day_in_study"]).reset_index(drop=True)


def _value(x):
    return None if pd.isna(x) else x


def to_records(frame: pd.DataFrame) -> list[DailyRecord]:
    """DailyRecords, source="real". Missing values are None, never 0."""
    records = []
    for row in frame.itertuples(index=False):
        bleeding = _value(row.bleeding)
        steps, sleep_min = _value(row.steps), _value(row.sleep_min)
        records.append(
            DailyRecord(
                user_id=row.user_id,
                date=row.date,
                rhr_bpm=_value(row.rhr_bpm),
                hrv_rmssd_ms=_value(row.hrv_rmssd_ms),
                skin_temp_dev_c=_value(row.skin_temp_dev_c),
                sleep_min=None if sleep_min is None else int(sleep_min),
                steps=None if steps is None else int(steps),
                checkin=None if bleeding is None else CheckIn(bleeding=bleeding),
                source="real",
            )
        )
    return records


def phase_labels(frame: pd.DataFrame) -> dict[tuple[str, date], str]:
    """Mira's phase per (user_id, date), mapped to the contract's Phase. The eval's ground truth."""
    known = frame.dropna(subset=["phase"])
    return dict(zip(zip(known["user_id"], known["date"], strict=True), known["phase"], strict=True))


# --- aggregates-only reports -------------------------------------------------------------------


def schema_report(root: Path | None = None) -> dict:
    """Expected column names vs the files' headers. Names only, no values."""
    root = root or data_dir()
    report = {}
    for name, cols in COLUMNS.items():
        path = root / f"{name}.csv"
        if not path.exists():
            report[name] = "file missing"
            continue
        header = list(pd.read_csv(path, nrows=0).columns)
        report[name] = {
            "missing": [c for c in cols if c not in header],
            "all_columns": header,
        }
    return report


def _hrv_match_rate(hrv_nights: pd.DataFrame, sleep_days: pd.DataFrame) -> float:
    """Share of HRV nights whose wake day also has a main sleep."""
    if hrv_nights.empty:
        return float("nan")
    hit = hrv_nights[KEY].merge(sleep_days[KEY], on=KEY, how="inner")
    return round(len(hit) / len(hrv_nights), 3)


def _median(s: pd.Series) -> float | None:
    s = s.dropna()
    return round(float(s.median()), 2) if len(s) else None


def summary(frame: pd.DataFrame, root: Path | None = None) -> dict:
    """Aggregates only: counts, % missing, percentiles, label counts and the HRV dating check."""
    out: dict = {"rows": len(frame), "rounds": {}}
    for rnd, g in frame.groupby("study_interval"):
        stats = {
            "participants": int(g["id"].nunique()),
            "participant_days": len(g),
            "phase_counts": g["phase"].value_counts(dropna=False).to_dict(),
            "bleeding_counts": g["bleeding"].value_counts(dropna=False).to_dict(),
            "signals": {},
        }
        for col in SIGNALS:
            s = g[col].dropna()
            stats["signals"][col] = {
                "pct_missing": round(100 * (1 - len(s) / len(g)), 1),
                "p25_p50_p75": [round(float(s.quantile(q)), 2) for q in (0.25, 0.5, 0.75)]
                if len(s)
                else None,
            }
        out["rounds"][str(rnd)] = stats
    # Same people in both rounds, so a 2022 vs 2024 gap isn't just a different group.
    in_both = frame.groupby("id")["study_interval"].nunique().loc[lambda n: n > 1].index
    same = frame[frame["id"].isin(in_both)]
    out["same_people_both_rounds"] = {
        "participants": len(in_both),
        "median_by_round": {
            col: {str(r): _median(g[col]) for r, g in same.groupby("study_interval")}
            for col in ("sleep_min", "hrv_rmssd_ms", "skin_temp_dev_c")
        },
    }
    # Which HRV dating rule lines up with sleep wake days (higher is better).
    raw_hrv = load(
        "heart_rate_variability_details",
        COLUMNS["heart_rate_variability_details"],
        root=root,
    )
    sleep_days = sleep(load("sleep", COLUMNS["sleep"], root=root))
    cov = pd.to_numeric(raw_hrv["coverage"], errors="coerce") if "coverage" in raw_hrv else None
    deduped = _round(raw_hrv.copy()).drop_duplicates(
        subset=["id", "study_interval", "day_in_study", "timestamp"]
    )

    def median_size(evening_hour):  # the right rule keeps a night whole (~90 samples)
        return float(_hrv_nights(deduped, evening_hour)["size"].median())

    out["hrv_dating_check"] = {
        f"shift_at_{HRV_EVENING_HOUR}h": _hrv_match_rate(hrv(raw_hrv.copy()), sleep_days),
        "day_as_is": _hrv_match_rate(hrv(raw_hrv.copy(), evening_hour=None), sleep_days),
        "share_samples_after_noon": round(float((_hour(deduped["timestamp"]) >= 12).mean()), 3),
        f"median_samples_per_night_shift_at_{HRV_EVENING_HOUR}h": median_size(HRV_EVENING_HOUR),
        "median_samples_per_night_day_as_is": median_size(None),
        # Sets the "drop low coverage" cutoff in docs/data.md, which has no number yet.
        "coverage_p5_p50_p95": [round(float(cov.quantile(q)), 3) for q in (0.05, 0.5, 0.95)]
        if cov is not None and cov.notna().any()
        else None,
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--schema", action="store_true", help="check column names only")
    args = parser.parse_args()
    if args.schema:
        print(json.dumps(schema_report(), indent=2))
        return
    frame = build_frame()
    print(json.dumps(summary(frame), indent=2, default=str))


if __name__ == "__main__":
    main()
