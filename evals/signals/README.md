# Signals eval: luteal-rise detector on held-out mcPHASES participants

Run: `python -m evals.signals.run` (needs your own mcPHASES download, D18; prints aggregates only).

## What it measures

Does the detector in `signals/detector.py` call a day "luteal-like" when Mira's hormone-based label
says `Luteal`, on people it was not tuned on?

- **Split by person:** a fixed hash of the participant id (`SALT` in `run.py`) puts 15 of 42 people
  in test, with both of their rounds. Nobody is in train and test.
- **Tuning on train only:** 36 settings (threshold scale, baseline and recent windows, signal set).
  Best = highest balanced accuracy with coverage of at least 0.6.
- **Ground truth:** Mira's `Luteal` label vs every other phase. Mira's labels come from its own
  algorithm on urine hormones, not ultrasound, so they are not a clinical measurement of ovulation.
  **Say this with any number below.**
- **Metrics:** coverage (share of labeled days with a verdict; the rest are "not enough data yet"),
  balanced accuracy, sensitivity, specificity, and detection lag (days from the first luteal-labeled
  day of a run to the first "luteal-like" verdict inside it). Always calling "not luteal" scores
  balanced accuracy 0.5.

## Results (2026-11-21, mcPHASES v1.0.0)

Chosen on train: all three signals, threshold scale 1.0 (0.10 °C, 1.0 bpm, 2.5 ms), 21-day baseline,
3-night recent window.

95% intervals resample the 15 test people (both rounds together) with replacement, 1,000 times
with a fixed seed. Days are not resampled: one person's nights are not independent.

| | People | Labeled days | Coverage | Balanced accuracy (95% CI) | Sensitivity | Specificity |
|---|---|---|---|---|---|---|
| Train | 27 | 3,605 | 0.65 | 0.73 | 0.80 | 0.66 |
| **Test** | **15** | **2,053** | **0.61 (0.53–0.65)** | **0.64 (0.55–0.73)** | **0.67** | **0.62** |
| Test, 2022 round | | 1,267 | 0.61 | 0.66 | 0.68 | 0.64 |
| Test, 2024 round (no RHR) | | 786 | 0.61 | 0.62 | 0.65 | 0.58 |

Signal sets on test (same windows and scale):

| Signals | Coverage (95% CI) | Balanced accuracy (95% CI) |
|---|---|---|
| Temperature only | 0.58 (0.49–0.63) | 0.60 (0.52–0.68) |
| Temperature + HRV | 0.55 (0.46–0.60) | 0.64 (0.56–0.72) |
| Temperature + HRV + RHR | 0.61 (0.53–0.65) | 0.64 (0.55–0.73) |

Paired differences in balanced accuracy (same resampled people): all three minus temperature only
−0.02 to +0.12; all three minus temperature + HRV −0.02 to +0.04. Both include 0.

Detection lag on test: 69 luteal runs, 70% detected, median 2 days after the labeled start
(p25–p75: 0–3).

## How to read it

- **There is signal, and it is modest.** 0.64 (0.55–0.73) on held-out people; even the low end is
  above 0.5 for guessing. About 4 in 10 decided non-luteal days are called luteal-like, so
  confidence stays "Low" (D28) and the app describes patterns, never phases as fact.
- **Train vs test gap (0.73 vs 0.64):** train sits at the top of the test interval, so the gap fits
  tuning plus small-sample noise. With 15 test people, quote the interval, not the second decimal.
- **We can't yet say the extra signals help.** Temperature alone (0.60, 0.52–0.68) is barely above
  guessing, and adding HRV and RHR looks better, but the paired differences include 0. RHR's clear
  effect is coverage (more days with a verdict), not accuracy. More people, not more tuning, would
  settle this.
- **Look-back only:** a 2-day median lag fits D34. The detector explains a rise after it happens and
  never predicts a date.
- **Not shown here:** calibration of a window, per-person results (D21), and anything about teens
  (everyone in mcPHASES is 18–29).
