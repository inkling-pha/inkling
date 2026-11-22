"""Held-out eval of the luteal-rise detector on mcPHASES: python -m evals.signals.run

Question: on people the rules were not tuned on, how often does "luteal-like" match Mira's
hormone-based phase label, and how many days after the luteal phase starts does it notice?

- **Split by person:** a fixed hash of the participant id puts ~30% of people in test, with both
  of their rounds, so nobody is in train and test.
- **Tuning on train only:** a small grid over the threshold scale, baseline and recent windows,
  and signal sets. Best = highest balanced accuracy with coverage of at least MIN_COVERAGE.
- **Ground truth:** Mira's `Luteal` label vs everything else. Labels come from urine hormones,
  not ultrasound (docs/data.md); say so with any number reported.

Prints aggregates only (D18, D21): counts, rates, medians. No ids, no rows, no per-person series.
Groups with fewer than MIN_GROUP people are suppressed. 95% intervals resample test people (not
days) with replacement.
"""

import hashlib
import itertools
import json
import random
import statistics
from collections import defaultdict
from datetime import date, timedelta

from signals import detector
from signals import mcphases_records as mr

TEST_SHARE = 0.3
SALT = "inkling-signals-eval-v1"  # changing it changes the split; log a new split in data.md
MIN_COVERAGE = 0.6
MIN_GROUP = 5
BOOTSTRAP = 1000  # resamples of test people for the 95% intervals

SIGNAL_SETS = {
    "all": ["skin_temp_dev_c", "rhr_bpm", "hrv_rmssd_ms"],
    "temp_only": ["skin_temp_dev_c"],
    "temp_hrv": ["skin_temp_dev_c", "hrv_rmssd_ms"],
}
GRID = {
    "scale": [0.5, 1.0, 1.5],
    "baseline_days": [21, 28],
    "recent_days": [2, 3],
    "signal_set": list(SIGNAL_SETS),
}


def is_test(participant: str) -> bool:
    digest = hashlib.sha256(f"{SALT}:{participant}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF < TEST_SHARE


def signals_for(signal_set: str, scale: float) -> dict[str, tuple[int, float]]:
    return {
        f: (detector.SIGNALS[f][0], detector.SIGNALS[f][1] * scale) for f in SIGNAL_SETS[signal_set]
    }


def predict(users: dict, params: dict) -> dict:
    """(user_id, date) -> True / False / None for every record."""
    sig = signals_for(params["signal_set"], params["scale"])
    out = {}
    for user_id, records in users.items():
        for s in detector.detect(records, sig, params["baseline_days"], params["recent_days"]):
            out[(user_id, s.date)] = s.luteal_like
    return out


def tally(preds: dict, labels: dict) -> list[int]:
    """[tp, fn, tn, fp, undecided] over labeled days that have a prediction."""
    tp = fn = tn = fp = undecided = 0
    for key, phase in labels.items():
        if key not in preds:
            continue
        p, luteal = preds[key], phase == "luteal"
        if p is None:
            undecided += 1
        elif luteal:
            tp, fn = tp + p, fn + (not p)
        else:
            fp, tn = fp + p, tn + (not p)
    return [tp, fn, tn, fp, undecided]


def _balanced_accuracy(tp: int, fn: int, tn: int, fp: int) -> float:
    if not (tp + fn and tn + fp):
        return float("nan")
    return (tp / (tp + fn) + tn / (tn + fp)) / 2


def bootstrap(per_person: dict[str, dict[str, list[int]]], n: int = BOOTSTRAP, seed: int = 0):
    """95% intervals from resampling test *people* with replacement (days within a person are
    not independent, so resampling days would make the intervals too narrow).

    per_person: person -> signal set -> tally. Returns intervals per set for balanced accuracy and
    coverage, plus paired intervals for "all" minus each other set (same resampled people).
    """
    rng = random.Random(seed)
    people = sorted(per_person)
    sets = list(next(iter(per_person.values()))) if people else []
    draws: dict[str, dict[str, list[float]]] = {s: {"ba": [], "cov": []} for s in sets}
    diffs: dict[str, list[float]] = {s: [] for s in sets if s != "all"}
    for _ in range(n):
        sample = [rng.choice(people) for _ in people]
        ba = {}
        for s in sets:
            tp, fn, tn, fp, und = (sum(per_person[p][s][i] for p in sample) for i in range(5))
            ba[s] = _balanced_accuracy(tp, fn, tn, fp)
            draws[s]["ba"].append(ba[s])
            decided = tp + fn + tn + fp
            draws[s]["cov"].append(decided / (decided + und) if decided + und else float("nan"))
        for s in diffs:
            diffs[s].append(ba["all"] - ba[s])
    return {
        "resamples": n,
        "balanced_accuracy_95ci": {s: _ci(d["ba"]) for s, d in draws.items()},
        "coverage_95ci": {s: _ci(d["cov"]) for s, d in draws.items()},
        "all_minus_set_balanced_accuracy_95ci": {s: _ci(d) for s, d in diffs.items()},
    }


def _ci(xs: list[float]) -> list[float] | None:
    xs = sorted(x for x in xs if x == x)  # drop NaN (a resample with no luteal days, say)
    if not xs:
        return None
    return [round(xs[int(0.025 * (len(xs) - 1))], 3), round(xs[int(0.975 * (len(xs) - 1))], 3)]


def score(preds: dict, labels: dict) -> dict:
    """Coverage, balanced accuracy, sensitivity and specificity on labeled days."""
    tp, fn, tn, fp, undecided = tally(preds, labels)
    decided = tp + fn + tn + fp
    sens = tp / (tp + fn) if tp + fn else float("nan")
    spec = tn / (tn + fp) if tn + fp else float("nan")
    return {
        "labeled_days": decided + undecided,
        "coverage": round(decided / (decided + undecided), 3) if decided + undecided else None,
        "balanced_accuracy": round((sens + spec) / 2, 3),
        "sensitivity": round(sens, 3),
        "specificity": round(spec, 3),
    }


def luteal_runs(labels: dict) -> list[tuple[str, date, date]]:
    """(user_id, first day, last day) for each run of consecutive luteal-labeled days."""
    by_user = defaultdict(list)
    for (user_id, day), phase in labels.items():
        if phase == "luteal":
            by_user[user_id].append(day)
    runs = []
    for user_id, days in by_user.items():
        days.sort()
        first = prev = days[0]
        for day in days[1:]:
            if (day - prev).days > 1:
                runs.append((user_id, first, prev))
                first = day
            prev = day
        runs.append((user_id, first, prev))
    return runs


def detection_lag(preds: dict, labels: dict) -> dict:
    """Per luteal run: days from its first day until the first luteal-like verdict inside it."""
    runs = luteal_runs(labels)
    lags = []
    for user_id, first, last in runs:
        hits = [
            (d - first).days
            for d in (first + timedelta(days=i) for i in range((last - first).days + 1))
            if preds.get((user_id, d)) is True
        ]
        if hits:
            lags.append(hits[0])
    return {
        "luteal_runs": len(runs),
        "share_detected": round(len(lags) / len(runs), 3) if runs else None,
        "median_lag_days": statistics.median(lags) if lags else None,
        "p25_p75_lag_days": [_quantile(lags, 0.25), _quantile(lags, 0.75)] if lags else None,
    }


def _quantile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main() -> dict:
    frame = mr.build_frame()
    labels = mr.phase_labels(frame)
    person = dict(zip(frame["user_id"], frame["id"].astype(str), strict=True))
    users = defaultdict(list)
    for r in mr.to_records(frame):
        users[r.user_id].append(r)
    split = {u: ("test" if is_test(person[u]) else "train") for u in users}
    by_split = {
        name: {u: rs for u, rs in users.items() if split[u] == name} for name in ("train", "test")
    }

    def labels_for(user_ids):
        return {k: v for k, v in labels.items() if k[0] in user_ids}

    train_labels = labels_for(set(by_split["train"]))
    test_labels = labels_for(set(by_split["test"]))

    grid = []
    for values in itertools.product(*GRID.values()):
        params = dict(zip(GRID, values, strict=True))
        grid.append((params, score(predict(by_split["train"], params), train_labels)))
    eligible = [g for g in grid if (g[1]["coverage"] or 0) >= MIN_COVERAGE] or grid
    best_params, best_train = max(eligible, key=lambda g: g[1]["balanced_accuracy"])

    test_preds = predict(by_split["test"], best_params)
    result = {
        "people": {name: len({person[u] for u in us}) for name, us in by_split.items()},
        "best_params": best_params,
        "train": best_train,
        "test": score(test_preds, test_labels),
        "test_detection_lag": detection_lag(test_preds, test_labels),
        "test_by_round": {},
        "test_by_signal_set": {},
        "reference": "always 'not luteal' scores balanced accuracy 0.5",
    }
    for rnd in ("2022", "2024"):
        ids = {u for u in by_split["test"] if u.endswith(f"-{rnd}")}
        if len(ids) >= MIN_GROUP:
            result["test_by_round"][rnd] = score(test_preds, labels_for(ids))
        else:
            result["test_by_round"][rnd] = f"suppressed (<{MIN_GROUP} people)"
    per_person: dict[str, dict[str, list[int]]] = defaultdict(dict)
    for name in SIGNAL_SETS:  # same windows and scale, different signals
        params = {**best_params, "signal_set": name}
        preds = predict(by_split["test"], params)
        result["test_by_signal_set"][name] = score(preds, test_labels)
        for p in {person[u] for u in by_split["test"]}:  # both rounds of a person together
            mine = {k: v for k, v in test_labels.items() if person[k[0]] == p}
            per_person[p][name] = tally(preds, mine)
    result["test_bootstrap"] = bootstrap(per_person)
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    main()
