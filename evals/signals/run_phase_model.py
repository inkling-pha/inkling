"""Held-out eval of the logistic phase model: python -m evals.signals.run_phase_model

Same held-out split and metrics as the rule detector (evals/signals/run.py), so the two are
directly comparable per D15: the ML model ships only if it beats the rules on held-out people.
Trains on train only; the test split never feeds back into training or feature choices.

Needs your own mcPHASES download (D18). Prints aggregates only — counts, rates, a few trained
weights (not participant rows). Don't commit the printed weights into the app until D15's DUA
question (may trained weights be shipped?) is answered; see signals/phase_model.py.
"""

import json
from collections import defaultdict

from evals.signals.run import bootstrap, detection_lag, is_test, score, tally
from signals import mcphases_records as mr
from signals import phase_model as pm

REFERENCE = (
    "rule detector (evals/signals/run.py, 2026-11-21): "
    "test balanced accuracy 0.64 (0.55-0.73), coverage 0.61"
)


def _training_rows(users: dict, labels: dict) -> tuple[list[list[float]], list[int]]:
    """Feature vector + label for every (user, day) with a ground-truth phase and some signal."""
    X, y = [], []
    for user_id, records in users.items():
        for day, row in pm.deltas_by_day(records).items():
            key = (user_id, day)
            if key not in labels or all(v is None for v in row.values()):
                continue
            X.append(pm.featurize(row))
            y.append(1 if labels[key] == "luteal" else 0)
    return X, y


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

    train_X, train_y = _training_rows(by_split["train"], labels)
    model = pm.train(train_X, train_y)

    test_preds = {}
    for user_id, records in by_split["test"].items():
        for day, (luteal_like, _prob) in pm.predict_days(records, model).items():
            test_preds[(user_id, day)] = luteal_like
    test_labels = {k: v for k, v in labels.items() if k[0] in by_split["test"]}

    per_person: dict[str, dict[str, list[int]]] = defaultdict(dict)
    for p in {person[u] for u in by_split["test"]}:
        mine_preds = {k: v for k, v in test_preds.items() if person[k[0]] == p}
        mine_labels = {k: v for k, v in test_labels.items() if person[k[0]] == p}
        per_person[p]["all"] = tally(mine_preds, mine_labels)  # bootstrap() expects "all"

    result = {
        "people": {name: len({person[u] for u in us}) for name, us in by_split.items()},
        "train_rows": len(train_y),
        "train_luteal_share": round(sum(train_y) / len(train_y), 3) if train_y else None,
        "model_weights": dict(zip(pm.FEATURE_NAMES, model.weights, strict=True)),
        "test": score(test_preds, test_labels),
        "test_detection_lag": detection_lag(test_preds, test_labels),
        "test_bootstrap": bootstrap(per_person),
        "reference": REFERENCE,
    }
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    main()
