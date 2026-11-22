"""A learned alternative to the rule-based luteal-rise detector (D15's "planned ML model").

Logistic regression over the same baseline-relative deltas signals/detector.py computes (temp,
RHR, HRV vs her own baseline), so it's comparable to the rules on the same held-out split
(evals/signals/run.py). Pure Python, no new dependency (ask before adding numpy/scikit-learn,
per CLAUDE.md) — three to six features and a few hundred people don't need one.

D15: ships only if it beats the rules on held-out test people. Until then this is an offline
result for the poster/writeup; nothing in signals/, agent/ or app/ calls it.

D15 also flags trained weights as a grey area under the mcPHASES DUA (D18): don't commit a
trained Model (save_weights'd) until the team or instructor has confirmed that's fine. Training
and evaluating it is not the grey area — only committing/shipping the result is.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta

from contracts import DailyRecord
from signals.detector import (
    BASELINE_DAYS,
    MIN_BASELINE_NIGHTS,
    MIN_RECENT_NIGHTS,
    RECENT_DAYS,
    _median_in,
)
from signals.detector import SIGNALS as RULE_SIGNALS

FEATURES = list(RULE_SIGNALS)  # same three signals as the rule detector, same order

L2 = 1.0  # fixed for v1 — a grid search here is a follow-up, once this proves worth tuning
LEARNING_RATE = 0.3
EPOCHS = 300


def deltas_by_day(
    records: list[DailyRecord],
    baseline_days: int = BASELINE_DAYS,
    recent_days: int = RECENT_DAYS,
) -> dict[date, dict[str, float | None]]:
    """Per day: recent-minus-baseline per signal, None if too few nights. Same windows as
    detector.detect(), so the two approaches see the same information."""
    series = {
        f: {r.date: getattr(r, f) for r in records if getattr(r, f) is not None} for f in FEATURES
    }
    out = {}
    for day in sorted({r.date for r in records}):
        recent_start = day - timedelta(days=recent_days - 1)
        row = {}
        for f in FEATURES:
            values = series[f]
            base = _median_in(
                values,
                recent_start - timedelta(days=baseline_days),
                recent_start - timedelta(days=1),
                MIN_BASELINE_NIGHTS,
            )
            recent = _median_in(values, recent_start, day, MIN_RECENT_NIGHTS)
            row[f] = None if base is None or recent is None else recent - base
        out[day] = row
    return out


def featurize(delta_row: dict[str, float | None]) -> list[float]:
    """[delta or 0, missing flag] per signal — lets the model use whichever signals a day has,
    rather than requiring all three (detector.py votes per-signal but a day with, say, only
    temperature still gets a verdict from that one vote; this is the ML equivalent)."""
    vec = []
    for f in FEATURES:
        d = delta_row[f]
        vec += [0.0 if d is None else d, 1.0 if d is None else 0.0]
    return vec


FEATURE_NAMES = [n for f in FEATURES for n in (f, f"{f}_missing")]


@dataclass(frozen=True)
class Model:
    weights: list[float]
    bias: float
    means: list[float]
    scales: list[float]  # standard deviations from training; never 0 (see _standardize)

    def predict_proba(self, x: list[float]) -> float:
        z = self.bias + sum(
            w * (xi - m) / s
            for w, xi, m, s in zip(self.weights, x, self.means, self.scales, strict=True)
        )
        return 1 / (1 + math.exp(-max(-60.0, min(60.0, z))))  # clamp: avoid math.exp overflow

    def to_json(self) -> str:
        """A few floats, not participant data — still don't commit this until D15's DUA
        question is answered. See this module's docstring."""
        return json.dumps(
            {"weights": self.weights, "bias": self.bias, "means": self.means, "scales": self.scales}
        )

    @staticmethod
    def from_json(text: str) -> Model:
        d = json.loads(text)
        return Model(d["weights"], d["bias"], d["means"], d["scales"])


def _standardize(xs: list[list[float]]) -> tuple[list[float], list[float]]:
    n, d = len(xs), len(xs[0])
    means = [sum(row[i] for row in xs) / n for i in range(d)]
    variances = [sum((row[i] - means[i]) ** 2 for row in xs) / n for i in range(d)]
    return means, [math.sqrt(v) or 1.0 for v in variances]  # a constant feature keeps scale 1


def train(
    X: list[list[float]],
    y: list[int],
    l2: float = L2,
    lr: float = LEARNING_RATE,
    epochs: int = EPOCHS,
) -> Model:
    """Logistic regression, batch gradient descent, L2 on the weights (not the bias)."""
    if len(X) != len(y) or not X:
        raise ValueError("train needs at least one row, X and y the same length")
    n, d = len(X), len(X[0])
    means, scales = _standardize(X)
    standardized = [[(row[i] - means[i]) / scales[i] for i in range(d)] for row in X]
    weights, bias = [0.0] * d, 0.0
    for _ in range(epochs):
        grad_w, grad_b = [0.0] * d, 0.0
        for row, label in zip(standardized, y, strict=True):
            z = bias + sum(w * xi for w, xi in zip(weights, row, strict=True))
            error = 1 / (1 + math.exp(-max(-60.0, min(60.0, z)))) - label
            for i, xi in enumerate(row):
                grad_w[i] += error * xi
            grad_b += error
        weights = [w - lr * (grad_w[i] / n + l2 * w / n) for i, w in enumerate(weights)]
        bias -= lr * grad_b / n
    return Model(weights, bias, means, scales)


def predict_days(
    records: list[DailyRecord], model: Model, threshold: float = 0.5
) -> dict[date, tuple[bool | None, float | None]]:
    """date -> (luteal_like or None, probability). None only when every signal is missing that
    day — same "not enough data yet" spirit as the rule detector, never a guess from nothing."""
    out = {}
    for day, row in deltas_by_day(records).items():
        if all(v is None for v in row.values()):
            out[day] = (None, None)
            continue
        p = model.predict_proba(featurize(row))
        out[day] = (p >= threshold, p)
    return out
