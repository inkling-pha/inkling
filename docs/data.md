# Data sources

Reference for building against our two data sources: how to get access, how the data is shaped,
and the quirks we've hit. It holds **no one's actual values**. Real data never goes in the repo.
Handling rules are in [CLAUDE.md](../CLAUDE.md) and decisions D18–D25 in [decisions.md](decisions.md).

- [Fitbit via the Google Health API](#fitbit-via-the-google-health-api): live data for the app
- [Periods from check-ins](#periods-from-check-ins): how logged bleeding becomes cycle history
- [mcPHASES](#mcphases): labeled research data for building and evaluating the phase model

---

## Fitbit via the Google Health API

Last checked: 2026-10-26, Fitbit Air, `notebooks/fitbit_test_pull.ipynb`. Parsing quirks added 2026-11-19.

### Access

- Access goes through the **course OAuth app** (BINF 4070, Lab 3), not our own Google Cloud project.
  1. Open the [course authorization helper](https://binf4070-health-oauth-helper-7pw5f3iaiq-ue.a.run.app/authorize)
     with the Google account your Fitbit syncs to.
  2. Grant all three read permissions: activity and fitness, health metrics and measurements, and sleep.
  3. Put the two values the helper gives you in `.env` as `GOOGLE_HEALTH_REFRESH_TOKEN` and
     `GOOGLE_HEALTH_HELPER_TOKEN`. Never paste them into a chat or an AI tool.
- The client exchanges that token pair at the helper's `/refresh` endpoint for a short-lived access
  token, which it keeps in memory only.
- The access is **read-only**. We can't write anything back to Google Health.
- If a token is exposed, revoke the course app in
  [Google Account connections](https://myaccount.google.com/connections), then authorize again.
- Code:
  - Client: `signals/google_health.py`
  - Test pull: `notebooks/fitbit_test_pull.ipynb`
  - Raw pulls are cached as `data/raw/fitbit/<type>_<start>_<end>.json` (gitignored, `"source": "real"`).
  - Parser: `signals/parse.py`. Store: `signals/store.py`. Sync: `signals/sync.py` (below).

### Sync

Pulls Fitbit data into the store. Built 2026-11-19 on D13 (proposed).

- **On app open, once per session:** `sync(user_id)` pulls from 3 days before the last stored day up
  to today. Overnight values arrive late and today's steps are partial, so the last few days are
  re-pulled and replaced. After a long absence it pulls at most 90 days.
- **History, once, by hand:** `python -m signals.sync --backfill 90`. Kept out of app load so it
  stays fast. Without `--backfill`, the same command runs a normal sync.
- **What it pulls:** resting HR, temperature, HRV samples (from one day earlier, since a night's
  samples start the evening before), sleep and steps. Each pull is cached raw, then only that window
  is parsed and saved.
- **Failures never raise.** No token or no network → `cached`: nothing stored changes. One type fails
  → `partial`: the rest are saved, and the fields that type feeds keep their stored values instead of
  becoming None. Every attempt is logged (`sync_log` table: time, mode, error), which gives "last
  synced". Errors record only the data type, error type and HTTP status, never bodies or tokens.
- **One Fitbit account per machine, saved as user `me`:** the tokens in `.env` belong to one account,
  and there is no login, so its data goes under the user id `me` (`--user` to override). Each
  teammate's `me` is their own data in their own gitignored DB. Without tokens, sync reports `cached`
  and the app shows the synthetic demo user. Multi-user is out of scope.
- **Switching Fitbit accounts on one machine?** Delete `data/inkling.db` and `data/raw/fitbit/` first,
  or both accounts' data ends up mixed under `me`.
- **Status for the app:** `sync` returns a signals-internal `SyncStatus` (mode, last successful sync,
  window, days saved, failed types). Showing it in the app needs a `SyncStatus` contract and an app
  hook (both pending: contracts v0.2 and the app owner).
- **Reading:** `get_daily_records(user_id)` returns the stored days. A user with nothing stored (such
  as the demo user) still gets the synthetic fixture, labeled `synthetic`.

### Endpoint

`GET https://health.googleapis.com/v4/users/me/dataTypes/{type}/dataPoints`
([reference](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/list))

| Param | Notes |
|---|---|
| `filter` | Date range ([AIP-160](https://google.aip.dev/160) syntax), e.g. `daily_resting_heart_rate.date >= "2026-10-01" AND daily_resting_heart_rate.date < "2026-10-08"`. Only `>=`, `<`, `AND` (and `OR` for sleep). |
| `pageSize` | Max 10,000, except 25 for `sleep`. |
| `pageToken` | Pass the `nextPageToken` from the previous page. An empty token means that was the last page. |
| `dataSourceFamily` | `all-sources` (default), `google-wearables`, `google-sources` or `self-sources`. Not allowed for `sleep`. |

- Results come newest first.
- Rate limit: 300 requests per minute per user.

### Data types

Every type below returned data through the course app. **Granularity** is how often the device
records that type, not how much any one person has.

| Signal | Type | Filter field | Key fields | Granularity |
|---|---|---|---|---|
| Skin temp | `daily-sleep-temperature-derivations` | `daily_sleep_temperature_derivations.date` | `nightlyTemperatureCelsius`, `baselineTemperatureCelsius`, `relativeNightlyStddev30dCelsius` | 1 per night |
| Resting HR | `daily-resting-heart-rate` | `daily_resting_heart_rate.date` | `beatsPerMinute`\*, `dailyRestingHeartRateMetadata.calculationMethod` | 1 per day |
| HRV | `daily-heart-rate-variability` | `daily_heart_rate_variability.date` | `averageHeartRateVariabilityMilliseconds`, `deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds`, `nonRemHeartRateBeatsPerMinute`\*, `entropy` | 1 per night |
| HRV samples | `heart-rate-variability` | `heart_rate_variability.sample_time.civil_time` | `rootMeanSquareOfSuccessiveDifferencesMilliseconds`, `metadata.highFrequencyPower`, `metadata.lowFrequencyPower` | every 5 min during sleep |
| Respiratory rate | `daily-respiratory-rate` | `daily_respiratory_rate.date` | `breathsPerMinute` | 1 per night |
| Resp. rate by sleep stage | `respiratory-rate-sleep-summary` | `respiratory_rate_sleep_summary.sample_time.civil_time` | `deepSleepStats`, `lightSleepStats`, `remSleepStats`, `fullSleepStats`, each with `breathsPerMinute`, `standardDeviation`, `signalToNoise` | about 1 per night |
| SpO2 | `daily-oxygen-saturation` | `daily_oxygen_saturation.date` | `averagePercentage`, `lowerBoundPercentage`, `upperBoundPercentage`, `standardDeviationPercentage` | 1 per night |
| SpO2 samples | `oxygen-saturation` | `oxygen_saturation.sample_time.civil_time` | `percentage` | every minute during sleep |
| Sleep | `sleep` | `sleep.interval.civil_end_time` | `interval` (start/end), `type` (e.g. `STAGES`), `stages[]` (`startTime`, `endTime`, `type` e.g. `AWAKE`), `shortAwakenings[]` (`startTime`, `endTime`), `summary`, `metadata` | per session; naps add sessions |
| Steps | `steps` | `steps.interval.civil_start_time` | `count`\*, `interval` | 1-minute intervals |
| Heart rate | `heart-rate` | `heart_rate.sample_time.civil_time` | not inspected yet | every ~3 s (~33k points/day) |

\* These numbers come back as strings (`"beatsPerMinute": "63"`). Convert them when parsing.

**Every other type in the [DataPoint reference](https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints)**
(checked by asking each for its latest point; "empty" means the permission works but this device
or person had nothing recorded):

| Result | Types |
|---|---|
| **Can't be read** ("List is not supported", write-only) | `menstrual-period`, `ovulation-test`, `symptoms`, `moods`, `floors` |
| **No permission** (403; outside the course app's scopes) | `nutrition-log`, `hydration-log`, `electrocardiogram`, `irregular-rhythm-notification` |
| **Allowed, empty** for a Fitbit Air | `core-body-temperature`, `blood-glucose`, `body-fat`, `altitude`, `vo2-max`, `daily-vo2-max`, `run-vo2-max`, `basal-energy-burned` |
| **Has data** (activity; not used yet) | `exercise`, `distance`, `active-zone-minutes`, `active-minutes`, `activity-level`, `sedentary-period`, `active-energy-burned`, `time-in-heart-rate-zone`, `daily-heart-rate-zones`, `swim-lengths-data` |
| **Has data** (manual entries) | `weight`, `height` |

What this means for Inkling:
- **All self-logged cycle data is write-only** (periods, ovulation tests, symptoms, moods). Period
  dates and symptoms must come from our own check-in.
- **Core body temperature** (basal body temperature) is not recorded by the Fitbit Air. It would
  need a thermometer or a manual log, so nightly skin temperature is our temperature signal.

### Shape of a data point

```jsonc
{
  "name": "users/<numeric Google account id>/dataTypes/...",   // only on some types; NEVER copy this
  "dataSource": {
    "recordingMethod": "DERIVED",               // or PASSIVELY_MEASURED
    "device": {"displayName": "Fitbit Air", "formFactor": "FITNESS_BAND"},
    "platform": "FITBIT",
    "application": {"packageName": "..."}       // present when a phone app recorded it
  },
  "dailyRestingHeartRate": { ... }              // one payload key, the type name in camelCase
}
```

- **Times:**
  - `physicalTime` / `startTime` / `endTime` are RFC-3339 UTC, paired with a `utcOffset` like `"-14400s"`.
  - `civilTime` is local time as an object: `{"date": {"year", "month", "day"}, "time": {"hours", "minutes", ...}}`.
  - Daily types have a `date` object in the same `{year, month, day}` form.
- **Which day a value belongs to:** sleep-derived daily values (temperature, HRV, RHR, SpO2, respiratory
  rate) are dated the day you **wake up**.
- **Missing data:** a missing day is no data point at all, never a zero.
- **Identifiers:** `name` contains the account's Google user id. It stays in the raw cache and never
  goes into records, fixtures or logs. Use our own `user_id`.

### Quirks we've hit

- **Long intraday ranges fail.** 35 days of `heart-rate` in one request returned HTTP 503. The client
  pulls in 7-day chunks.
- **Temporary server errors.** `steps` and `sleep` sometimes return 500/503 on a request that worked
  minutes earlier. The client retries 429 and 5xx errors with backoff.
- **Steps can come from the phone.** Step points with `dataSource.application.packageName` are from
  a phone app. Use `dataSourceFamily=google-wearables` if we want watch-only steps.
- **Temperature is not a deviation.** The API returns the nightly value plus Fitbit's own baseline, so
  the deviation is nightly minus baseline. The first night or so after setup may have no value.
- **Filter field names** in snake_case (as in Lab 3) work. The docs also show camelCase
  (`dailyHeartRateVariability.date`).
- **`"NaN"` as a string.** `baselineTemperatureCelsius` and `relativeNightlyStddev30dCelsius` can be
  the string `"NaN"`, seemingly before a baseline exists. Treat it as missing. SQLite would otherwise
  store a NaN as NULL without saying so.
- **Numbers as strings, per field.** Within one type some fields are numbers and others strings
  (temperature: `nightlyTemperatureCelsius` is a number, `baselineTemperatureCelsius` a string).
  `sleep.summary.minutesAsleep` and `steps.count` are strings too.
- **Sleep has no civil time.** Only UTC `interval.startTime`/`endTime` plus `endUtcOffset`. The wake-up
  day is the local date of `endTime + endUtcOffset`.
- **Sleep flags overlap.** `metadata.mainSleep` and `metadata.nap` are independent: a session can be
  flagged both, and a nap may have no `mainSleep` at all. We go by `mainSleep`.
- **`minutesAsleep` counts short awakenings as sleep.** `summary.minutesAsleep` equals the sum of the
  non-`AWAKE` stage durations for every session checked. Brief wakes are listed separately in
  `shortAwakenings[]` (start/end), and every one checked fell *inside* a non-`AWAKE` stage. So the
  summary includes them as sleep, unlike mcPHASES (see below). We compute `sleep_min` ourselves.
- **Phone and watch steps don't overlap.** In one month of `all-sources` data, no minute had both a
  phone and a watch count. Phone steps fill time the watch was off, and some days are phone-only.

### Mapping to `DailyRecord`

Decided 2026-11-19 (Grace) for the parser in `signals/parse.py`. Every value is dated by the day it
belongs to, sleep-derived values by the wake-up day. A day with no data for a signal gets `None`,
never 0. Records are `source: "real"`.

| Contract field | Source | Choice and trade-off |
|---|---|---|
| `rhr_bpm` | `daily-resting-heart-rate.beatsPerMinute`, by its `date` | none |
| `hrv_rmssd_ms` | Mean of the 5-min `heart-rate-variability` RMSSD samples inside the main sleep session, by wake-up day. Needs 12+ samples (1 h), else `None` | Our own nightly mean, not Fitbit's `averageHeartRateVariabilityMilliseconds`, so it is computed the same way as mcPHASES (D25). It won't match the number in the Fitbit app |
| `skin_temp_dev_c` | `nightlyTemperatureCelsius − baselineTemperatureCelsius`, by its `date`. `None` if either is missing or `"NaN"` | `relativeNightlyStddev30dCelsius` is not kept: no contract field |
| `sleep_min` | Main sleep (`mainSleep: true`; the longest if several), by wake-up day: asleep-stage minutes (`LIGHT`, `DEEP`, `REM`, `ASLEEP`) minus the `shortAwakenings` inside them. Falls back to `summary.minutesAsleep` if a session has no stages | Computed like mcPHASES `minutesasleep` (decided 2026-11-19, for consistency). It reads lower than the Fitbit app's number, so the UI must not call it "what Fitbit says". Naps are not counted, matching the mcPHASES cleaning rule; a day with a big nap reads as short sleep |
| `steps` | Sum of `steps.count` per `civilStartTime` day, watch and phone together | Matches the Fitbit app's total, and no double counting was seen. mcPHASES steps are watch-only |
| (new?) | `daily-respiratory-rate.breathsPerMinute` | Not parsed. Needs a contract change (v0.2?) |

Parsed records and check-ins are stored in SQLite (`signals/store.py`, `data/inkling.db`,
gitignored). Re-saving a day replaces it. Check-ins are kept in their own table, so re-parsing
Fitbit data never overwrites them.

**Check-ins are stored as whole JSON**, one per user per day (the latest wins), not one column per
question, because the questions are not final (D5, D25). Adding a `CheckIn` field needs no change
here. A contract change that removes, renames or rescales a field needs a conversion step for stored
check-ins in the same PR (each stored check-in keeps its `schema_version`).

**Sleep stages (signals-internal, not in the contracts).** The main sleep's `stages[]` segments
(`LIGHT`, `DEEP`, `REM`, `AWAKE`, each with a UTC start and end) and its `shortAwakenings[]` (stored as
stage `SHORT_AWAKENING`, overlapping the stage they sit in) are kept per wake-up day in their own
table, because mcPHASES `sleep.levels` has the same detail (see
[Sleep stage detail](#sleep-stage-detail-sleeplevels)). If the app or the agent needs stage minutes,
that becomes a `DailyRecord` change through the contract process.

---

## Periods from check-ins

Fitbit's period log can't be read through the API (write-only, see [Data types](#data-types)), so
cycle history comes only from the bleeding answer in check-ins (`signals/cycle.py`). The numbers are
named constants there, set from mcPHASES (see [Cycles and periods](#cycles-and-periods-hormones_and_selfreport)).

| What | Rule | Why |
|---|---|---|
| Period start (day 1) | A `light`, `medium` or `heavy` day with no such day in the 10 days before | Spotting alone can be mid-cycle, so it never starts a period. On mcPHASES it found 101 of 116 of Mira's period starts, and 111 of the 117 starts it found matched one |
| Period end | The last bleeding day (spotting included) no more than 2 days after the previous one | One skipped check-in doesn't split a period |
| Usual cycle and period length | Medians of her last 6, once she has 2. Until then 29 and 6 days | The mcPHASES medians |
| Phase | The standard four phases. Menstrual through her period length (longer if she's still bleeding). Ovulatory = (usual length − 12) ± 1 day. Follicular before it, luteal after | Calendar method. 12 sits between the textbook 14 and mcPHASES, where Mira's fertile window ends a median 10 days before the next period. Ovulatory stays narrow on purpose: Mira's fertile window is wider, but matching it would read as fertile days (D25), so the eval will score lower on that phase |
| Later than usual | Past her usual length + 7 days, or past 38 days: phase `unknown`. It never wraps into a new cycle | A late period isn't a new cycle |
| No period logged | Phase `unknown`, `cycle_day` None, confidence 0 | No guessing from a default day 1 |
| `days_since_last_period` | Days since day 1 (0 on day 1). None with no start, or when the bleeding question hasn't been answered in 14 days | For the 90+ day rule: not logging is not the same as not bleeding |

- **Confidence** is a fixed 0.3 ("Low", D28) for every calendar estimate. Her history doesn't raise
  it, because accuracy isn't measured yet. The held-out eval sets it later.
- **No fertility timing (D25, D27).** The ovulation day is estimated only to place the phase
  boundaries. `ovulation_est_date` and `ovulation_window` are always None. The demo fixture still
  has them filled in.
- **Birth control (interim rule).** If any check-in in the last 35 days has `bc_taken=True`, the
  phase is `unknown` and `cycle_day` is None. Period starts and `days_since_last_period` still work,
  since they describe bleeding, not hormones. Why, from the trusted corpus:
  - Combined pill, patch and ring work mainly by stopping ovulation, and the bleed in the
    hormone-free days is a withdrawal bleed that follows the pack (CDC US SPR, pmid-34367655).
  - Progestin-only pills: norethindrone/norgestrel stop ovulation in about half of cycles, varying
    widely by person; drospirenone pills mainly stop it (CDC US SPR).
  - Shot, implant and IUDs list missed, irregular or lighter periods as expected effects (OWH). The
    corpus doesn't say which LARC methods stop ovulation.
  - Copper IUD and barrier methods have no hormones, so phases apply.
  - On combined pills, HRV and resting heart rate follow the pill pack, not a natural cycle
    (pmid-34367655, pmid-41545627). mcPHASES excludes hormonal contraception, so the eval can't test this.

  Limits: `bc_taken` ("taken today", yes/no) only fits pills and can't tell combined from
  progestin-only. A per-method rule needs a "which method" question, which is a contract change.
- **Cycle lengths assume she logs every period.** A missed period start reads as one long cycle.
- **The demo user** (nothing stored) keeps the fixture estimate. A user with anything stored gets the
  calendar estimate, which is `unknown` until she logs a period.

---

## mcPHASES

Last checked: 2026-10-27, mcPHASES v1.0.0, `notebooks/mcphases_eda.ipynb` (section 6 reproduces
every cleaning number below).

Access is under PhysioNet's **restricted-access DUA**:
- Everyone gets their own access and download: see [data/README.md](../data/README.md#getting-mcphases),
  which also lists which files we use and why.
- Claude never reads the raw files.
- This section holds only **schema and aggregates**: column names, types, counts, % missing,
  percentiles. Never rows, and never one participant's series.

### The study

- **42 participants** (menstruating adults, no recent hormonal contraception), wearing a
  **Fitbit Sense** and testing urine hormones daily with a **Mira** monitor.
- **Two rounds:** 2022 (all 42) and 2024 (20 of them). About 90 days per participant per round.
- **No calendar dates.** Time is `day_in_study`: the 2022 round is days 1–90, and the 2024 round is
  roughly days 850–997 (the day count doesn't restart). Treat each (participant, round) as its own
  sequence and never bridge the gap.
- **Join keys:** `id` + `day_in_study`. Sleep-based tables use `sleep_start_day_in_study` /
  `sleep_end_day_in_study` (the wake-up day, like the API). Every table has `study_interval`
  (2022/2024) and `is_weekend`.
- **The dataset authors did no cleaning** beyond phase labeling, so the duplicates and quirks below
  come from Fitbit's export. See [Cleaning](#cleaning).

### What's usable per round

| Data | 2022 | 2024 |
|---|---|---|
| Phase labels, hormones | yes | yes (LH runs higher: median 6.0 vs 3.8 mIU/mL for the same 20 people) |
| Self-report (flow, symptoms) | yes | mostly missing (the diary was optional) |
| Skin temp, HRV, respiratory rate, sleep | yes | yes, after removing duplicate rows |
| **Resting heart rate** | yes | **no**: conflicting copies per day ([why](#why-2024-rhr-and-steps-are-left-out)) |
| **Steps** | yes | **no**: conflicting copies, inflated totals |
| Active minutes | yes | yes, without `sedentary` |
| Exercise, active zone minutes, heart-rate zones | yes | yes (zone columns reversed) |

### Phase labels and hormones (`hormones_and_selfreport`)

| What | Values | Notes |
|---|---|---|
| `phase` | `Menstrual`, `Follicular`, `Fertility`, `Luteal` | On essentially every day for all 42 participants. ~1,080 menstrual days, so roughly 200 cycles |
| `lh` (mIU/mL), `estrogen` (E3G, ng/mL) | median 4.4 / 100 | 5.7% missing |
| `pdg` (PdG, mcg/mL) | median 3.4 | **67% missing** |

- **The labels come from Mira's own algorithm** working from urine hormones, not from a medical
  measurement of ovulation (no ultrasound). Say so whenever we report accuracy.
- **`Fertility` is a fertile window, not ovulation day.** Our contract's `Phase` has `ovulatory`;
  see the mapping below.

### Self-report (`hormones_and_selfreport`)

- About **41% of days are missing**, most of them in 2024.
- Symptoms (`cramps`, `bloating`, `fatigue`, `headaches`, `moodswing`, `stress`, ...) are **text**,
  not the 0–5 numbers the README describes: `Not at all`, `Very Low/Little`, `Low`, `Moderate`,
  `High`, `Very High`. A handful of rows hold stray numbers 1–5. Map them to ordered levels before use.
- `flow_volume` has 8 levels: `Not at all`, `Spotting / Very Light`, `Light`, `Somewhat Light`,
  `Moderate`, `Somewhat Heavy`, `Heavy`, `Very Heavy`.
- `flow_color` includes `Bright Red`, `Dark Brown / Dark Red`, `Pink`, `Orange`, `Yellow`, `Grey`,
  `Black`, `Other`.

### Cycles and periods (`hormones_and_selfreport`)

Checked 2026-11-19 with a person-run aggregate script. Reference periods are runs of Mira's
`Menstrual` label; runs cut off at the start or end of a round are left out.

| What | p10 | p25 | p50 | p75 | p90 | n |
|---|---|---|---|---|---|---|
| Cycle length (days) | 23 | 27 | 29 | 32 | 36 | 119 |
| Period (`Menstrual` run) length | 3 | 5 | 6 | 7 | 8 | 170 |
| Days from the end of the `Fertility` window to the next period | 5 | 9 | 10 | 12 | 13 | 162 |
| SD of cycle length within one person's round | 0.7 | 1.4 | 2.8 | 4.2 | 9.2 | 47 |

- **16 of 119 cycles (13%) were outside 24–38 days**, in people with no known cycle problems. A
  caution that fires on one such cycle will fire often.
- **The diary covers 116 of 181 Mira period starts** (a logged day within ±2 days).
- **The first logged bleeding day is a median 1 day after Mira's start**, and it is spotting in 29 of
  110 periods.
- **Day-1 rule** (a start must match a Mira start within ±2 days):

| Rule | Found | Correct |
|---|---|---|
| Light or heavier, 10-day gap (**used**) | 101 / 116 | 111 / 117 |
| Light or heavier, 7-day gap | 101 / 116 | 111 / 119 |
| Light or heavier, 3-day gap | 104 / 116 | 115 / 138 |
| Spotting or heavier, 10-day gap | 102 / 116 | 113 / 120 |
| Light or heavier, 14-day gap | 98 / 116 | 108 / 114 |

### Wearable signals and how they line up with the Google Health API

| Signal | mcPHASES | Per night | Typical values (p25–p75) | Google Health API |
|---|---|---|---|---|
| Skin temp deviation | `computed_temperature`: `baseline_relative_sample_sum / temperature_samples` | 1 (more with naps) | −0.35 to +0.33 °C | `nightlyTemperatureCelsius − baselineTemperatureCelsius` |
| Skin temp (absolute) | `computed_temperature.nightly_temperature` | 1 | 33.2–34.4 °C | `nightlyTemperatureCelsius` (same scale) |
| RHR | `resting_heart_rate.value` | 1 | 64–74 bpm\* | `daily-resting-heart-rate` |
| HRV | `heart_rate_variability_details.rmssd`, 5-min samples | ~90 (~7.5 h) | 31–69 ms | `heart-rate-variability` (same 5-min RMSSD) |
| Respiratory rate | `respiratory_rate_summary.full_sleep_breathing_rate` | 1 per sleep session | 14.4–16.8 /min | `respiratory-rate-sleep-summary` |
| Sleep | `sleep.minutesasleep`, `mainsleep` | 1+ (naps) | 297–459 min asleep | `stages[]` minus `shortAwakenings[]`, `metadata.mainSleep` (not `summary.minutesAsleep`, which counts short wakes as sleep) |

HRV and respiratory rate cover 40 of the 42 participants; the rest cover all 42.
\* Includes the unusable 2024 copies; the 2022-only range is in notebook section 6d.

#### Sleep stage detail (`sleep.levels`)

Checked 2026-11-19 with a script that prints aggregates only (14,765 sleep rows, before deduplication).

- **Stored as text in two encodings:** 10,654 rows are JSON, 4,111 are Python-literal (single
  quotes). A loader must accept both.
- **Shape:** a dict with `summary` and `data`, plus `shortData` on stages nights. Every entry is
  `{dateTime, level, seconds}`. Segments vary in length (p5/p50/p95: 90 / 780 / 3,360 s), always a
  multiple of 30 s, so they line up with the API's `stages[]` without resampling.
- **Two night types:**
  - `stages` (12,328, 83%): levels `deep`, `light`, `rem`, `wake`. Same as the API's `DEEP`, `LIGHT`,
    `REM`, `AWAKE`.
  - `classic` (2,437, 17%): levels `asleep`, `restless`, `awake`, no stage detail. Leave these out of
    stage comparisons.
  - 24 entries have level `unknown`.
- **`shortData` = the API's `shortAwakenings`:** brief `wake` entries laid over the `data` segments.
- **`minutesasleep` excludes short wakes.** On stages nights it equals asleep-level seconds in `data`
  minus the `shortData` wake seconds inside them (10,525 of 12,328 nights within 1 min, median
  difference 0). Counting only `data` overestimates by a median ~20 min (p25–p75: 15–26). Classic nights
  match on `asleep` seconds alone (2,403 of 2,437). The ~15% of stages nights that still differ have
  not been explained (possibly the 2024 duplicates). This is why our Fitbit `sleep_min` is computed
  the same way rather than taken from the API summary.

### Activity (confounder, and activity by phase)

| File | Grain | Participants | Typical values (p25–p75) | Google Health API |
|---|---|---|---|---|
| `steps` | 1 row per minute with data | 42 | 0–9 per minute; median ~6,200/day in 2022 | `steps` (1-min intervals) |
| `active_minutes` | 1 per day | 42 | light 90–228, moderate 0–21, very 0–23 min | `active-minutes` |
| `exercise` | 1 per session | **31** | 18–34 min, avg HR 102–118 | `exercise` |
| `active_zone_minutes` | 1 per minute in a zone | 42 | 1 per row; `heart_zone_id` is text | `active-zone-minutes` |
| `time_in_heart_rate_zones` | 1 per day | 42 | minutes below zone 1 and in zones 1–3 | `time-in-heart-rate-zone` |

- **Exercise is mostly passive:** 98% of sessions are `auto_detected` (the shortest is ~15 min,
  Fitbit's auto-detect threshold), so it shows what people did, not what they chose to log. Types with
  5+ participants: Walk 31, Aerobic Workout 20, Sport 18, Outdoor Bike 16, Run 9, Swim 8, Hike 6.
- **Heart-rate zones rarely cover a full day:** only 29% of days add up to ~1,440 min (partial wear).

### Cleaning

Apply these before any modeling. The [one-value-per-day table](#one-value-per-day) is the recipe.

**Keys and missing values**
- **Timestamps are time of day only** (`HH:MM:SS`), so every key needs the day column too.
- **Sentinels mean missing:** RHR `value == 0` (with `error == 100`); respiratory rates of `0` or `-1`;
  a temperature deviation of exactly `0` (1.6% of nights, probably before a baseline existed).
- **Units:** `exercise.duration` and `activeduration` are in **milliseconds**.

**Duplicates.** Some keys appear more than once. *Removed* is the share of rows that deduplication
deletes (a minute listed 3 times keeps 1 row and loses 2). Exact copies are safe to drop. Where
copies disagree, the rule says which to keep. The 2022 round has duplicates only in `exercise`.

#### One value per day

| File | Key | Duplicates (removed) | Rule |
|---|---|---|---|
| `hormones_and_selfreport` | `id`, `day_in_study` | none | As is |
| `computed_temperature` | `id`, `sleep_start_day_in_study`, `sleep_start_timestamp` | 17% of 2024, exact | Drop copies. Deviation = `baseline_relative_sample_sum / temperature_samples`, median per wake day |
| `heart_rate_variability_details` | `id`, `day_in_study`, `timestamp` | 5% of 2024, exact | Drop copies. Mean of 5-min `rmssd` per night (drop low `coverage`) |
| `respiratory_rate_summary` | `id`, `day_in_study`, `timestamp` | 14% of 2024, exact | Drop copies. Median of positive values per day (several rows per day are real: one per sleep session) |
| `sleep` | `id`, `sleep_start_day_in_study`, `sleep_start_timestamp` | 7% of 2024; values agree in 99% (the stage-detail string `levels` often differs) | Keep the longer `minutesasleep` per session, then the `mainsleep` session per wake day |
| `resting_heart_rate` | `id`, `day_in_study` | 80% of 2024, ~5 copies per day that **disagree** | **2022 only.** Drop zeros |
| `steps` | `id`, `day_in_study`, `timestamp` | 57% of 2024, copies **disagree** | **2022 only.** Sum per day |
| `active_minutes` | `id`, `day_in_study` | 4% of 2024, exact | Drop copies. `sedentary` exists only in 2022 |
| `exercise` | `id`, `start_day_in_study`, `start_timestamp` | 82% of 2022, 5% of 2024; values agree (`activezoneminutes` text sometimes differs) | Keep one per session. Take zone minutes from `active_zone_minutes` |
| `active_zone_minutes` | `id`, `day_in_study`, `timestamp`, `heart_zone_id` | 4% of 2024, exact | Drop copies. Sum per zone per day |
| `time_in_heart_rate_zones` | `id`, `day_in_study` | 5% of 2024, exact | Drop copies. **In 2024 the columns are reversed:** `in_default_zone_3`→below zone 1, `in_default_zone_2`→zone 1, `in_default_zone_1`→zone 2, `below_default_zone_1`→zone 3 |

**After cleaning, assert one row per (`id`, round, day)** before merging tables. Merging tables that
still hold several rows per day silently multiplies rows and misaligns labels, a bug
[womens-health-ml](https://github.com/YaaOppong/womens-health-ml) reports hitting.

#### Why 2024 RHR and steps are left out

- **RHR:** each 2024 day has ~5 copies, ~17–22 bpm apart (p25–p50), and 28% include a 0. No copy can
  be identified as the right one. The table has no timestamp, the values don't come from neighbouring
  days, and no copy position forms a believable series: each changes ~5 bpm a day at the median,
  against ~1 bpm in 2022. The dataset authors' example code takes the median of the copies
  ([chai-toronto/mcphases](https://github.com/chai-toronto/mcphases)), but a median of noisy copies
  is still noisy.
- **Steps:** in 2024, most duplicated minutes have one copy at 0 and another with a count. Even taking
  the max per minute, the 20 people in both rounds average a median of ~26,400 steps/day in 2024
  against ~6,200 in 2022 (~31,000 if the copies are summed).
- Every other 2024 signal matches 2022 for the same 20 people (HRV 44 vs 48 ms, temperature 33.8 vs
  33.7 °C, respiratory rate 15.4 vs 15.4 /min, light activity 175 vs 165 min), so the rest of 2024 is
  kept.

### Who is in the data (`subject-info`, one column at a time, groups under 5 suppressed)

- **Age in 2022:** under 20: 17, 20–24: 20, 25–29: 5. So **18–29, nobody under 18**: a good fit
  for young adults, but results can't be claimed for teens.
- **Ethnicity:** East Asian 14, Southeast Asian 10, White 9, Middle Eastern 5, others under 5 each.
  Worth noting because optical sensors can behave differently across skin tones.
- **Age at first period:** mostly 11–12. **Menstrual-health literacy:** mostly medium or high.

### Mapping to the contracts (proposal, not decided; see D25)

| Contract | From mcPHASES | Open question |
|---|---|---|
| `PhaseEstimate.phase` | `Menstrual`→`menstrual`, `Follicular`→`follicular`, `Fertility`→`ovulatory`, `Luteal`→`luteal` | Is "ovulatory" honest for a fertile window, and how do we keep the UI from reading as contraception advice? |
| `DailyRecord.skin_temp_dev_c` | nightly mean deviation (above) | Confirm it matches the API's nightly minus baseline |
| `DailyRecord.hrv_rmssd_ms` | nightly mean of 5-min `rmssd` (drop low `coverage`) | Decided: the Fitbit parser computes the same nightly mean from API samples. The API has no `coverage`, so it needs 12+ samples instead |
| `DailyRecord.rhr_bpm` | `resting_heart_rate.value`, **2022 round only** | Leaves about 3,700 participant-days |
| `DailyRecord.sleep_min` | `minutesasleep` of the main sleep | Decided: main sleep only, no naps. Same definition as our Fitbit parser (short wakes excluded) |
| `DailyRecord.steps` | per-minute `steps` summed per day, **2022 round only** | none |
| `CheckIn.bleeding` | `flow_volume`: Not at all→none, Spotting→spot, Light + Somewhat Light→light, Moderate→medium, Somewhat Heavy + Heavy + Very Heavy→heavy | none |
| `CheckIn.pain` (0–10) | `cramps` (6 text levels) | Rescale, or change the contract to the same 6 levels? |
| (new?) respiratory rate | `full_sleep_breathing_rate` | Add in v0.2? Both sources have it |

### Building `DailyRecord`s (`signals/mcphases_records.py`)

Checked 2026-11-21 by running `python -m signals.mcphases_records` on mcPHASES v1.0.0. It prints
aggregates only; the numbers below come from that output. `--schema` confirmed every column the
builder reads exists under the name used here.

**What it builds.** One row per (participant, round, day) with a row in `hormones_and_selfreport`,
then `DailyRecord`s (`source="real"`) and Mira's phase per day (the eval's ground truth). It asserts
one row per key for every table and after the merge.

| | 2022 | 2024 |
|---|---|---|
| Participants / participant-days | 42 / 3,698 | 20 / 1,961 |
| Days with a phase label | all but 1 | all |
| `bleeding` missing | 14% | **100%** (no diary in 2024) |
| `rhr_bpm` missing | 21% | 100% (left out on purpose) |
| `hrv_rmssd_ms` missing | 23% | 1% |
| `skin_temp_dev_c` missing | 15% | 7% |
| `sleep_min` missing | 7% | 0.3% |
| `steps` missing | 3% | 100% (left out on purpose) |

**Choices made in the builder**
- **user_id** is `mcphases-<id>-<round>`: each round is its own sequence with its own baselines, and
  the gap between rounds is never bridged. These ids stay local; they never appear in output.
- **date** = 2000-01-01 + `day_in_study` days. mcPHASES has no calendar dates; only the differences
  between dates mean anything, and this date is never shown as real.
- **HRV night:** a 5-min sample at or after 12:00 counts toward the next day's night (the wake day,
  like the Fitbit parser). Only 5.4% of samples are after noon, so this barely matters: both rules
  give a median of 90 samples per night, and 99.7% of HRV nights land on a day with a main sleep.
- **HRV coverage:** no cutoff applied. Coverage p5/p50/p95 is 0.86 / 0.99 / 1.0, so any reasonable
  cutoff drops very little. Nights still need 12+ samples, like the Fitbit parser.
- **checkin:** only `bleeding`. `pain` stays `None` until D25 settles how `cramps` maps to 0–10.
- **Steps** come out lower than in the EDA (median 5,700 vs ~6,200) because only days with a hormone
  row are kept.

**Unexplained: 2024 sleep is ~1.7 h longer.** For the 20 people in both rounds, median `sleep_min`
is 413 in 2022 and 516 in 2024, while HRV (45 vs 50 ms) and temperature deviation (0.0 vs −0.01 °C)
barely move. Possible causes: season (day ~850 lands around summer 2024) or a 2024 export quirk
the duplicate rule doesn't catch. It doesn't affect phase evals, since baselines are per round, but
don't pool raw sleep minutes across rounds.

## Synthetic Maya (`data/synthetic/maya.json`)

The demo persona from PRODUCT.md, generated by `signals/synthetic.py` from the mcPHASES
**aggregates** above. No participant's series is used. Every record is `source="synthetic"`, and
the app must label her as synthetic wherever her data appears.

- **158 days:** four finished cycles (29, 35, 27, 33 days) and a current cycle at day 34, later than
  her usual (~31). This sets up the hero question "My period is late again and I'm exhausted".
  Ovulation in the current cycle is late (day 22), so her temperature is still raised.
- **Signals:** her own levels plus the mcPHASES luteal shifts (temperature +0.23 °C, RHR +2.5 bpm,
  HRV −5.4 ms) and day-to-day noise (SD 0.12 °C, 1.6 bpm, 5 ms). In the saved file the luteal minus
  follicular means come out at +0.22 °C, +3.0 bpm and −4.5 ms.
- **Gaps:** about 10% of nights have no wearable data (16% in the saved file, close to mcPHASES), and
  she skips about 15% of check-ins outside her period.
- **Check-ins:** bleeding on period days (medium, heavy, medium, light, light, spot), cramps and pain
  on days 1–2, some bloating in the luteal phase, low energy and fatigue in the last 5 days.
- **truth:** the file also holds each day's phase and cycle day for tests. Never show it in the app;
  it is not a prediction (D25, D27, D34).
- **Dates:** the saved file ends on 2026-12-11 (showcase day). `synthetic.load()` shifts every date so
  the last day is today, so the demo always looks current. Regenerate with
  `python -m signals.synthetic --end YYYY-MM-DD`; the seed is fixed, so the values don't change.
