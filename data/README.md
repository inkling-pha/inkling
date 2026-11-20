Everything in `data/` is gitignored except this file and `data/synthetic/`.

- `data/raw/`: local only.
  - `data/raw/mcphases/`: your own mcPHASES download (PhysioNet terms forbid redistribution).
    Claude is denied this folder; see CLAUDE.md.
  - `data/raw/fitbit/`: real Fitbit pulls (label `source: real`).
- `data/inkling.db`: the signals SQLite store (parsed daily records, check-ins, sleep stages).
  Local only; created on first save. See [docs/data.md](../docs/data.md#mapping-to-dailyrecord).
- `data/synthetic/`: generated data that is safe to commit. Label it `source: synthetic`.

How each source is accessed and structured: [docs/data.md](../docs/data.md).

## Getting mcPHASES

mcPHASES is **restricted access** on PhysioNet. Every teammate gets their own access and their
own download. Never share files, logins or the data itself, including with AI tools (D18).

1. **Create a PhysioNet account** at <https://physionet.org/register/>.
2. **Sign the data use agreement:** open <https://physionet.org/content/mcphases/1.0.0/>, scroll
   to *Files*, and follow the steps to request access and sign the DUA. Complete anything else the
   page asks for. The download only works after this.
3. **Install wget** if you don't have it (`brew install wget` on macOS).
4. **Download only the files we use** (from the repo root). Use this instead of the `wget -r`
   command on the PhysioNet page: that one downloads every file, including a 616 MB file we
   don't need.

   ```bash
   caffeinate -i wget -c --tries=20 --waitretry=10 --read-timeout=60 \
     -P data/raw/mcphases --user YOUR_PHYSIONET_USERNAME --ask-password \
     -B https://physionet.org/files/mcphases/1.0.0/ -i - <<'EOF'
   README.txt
   LICENSE.txt
   SHA256SUMS.txt
   hormones_and_selfreport.csv
   subject-info.csv
   computed_temperature.csv
   resting_heart_rate.csv
   heart_rate_variability_details.csv
   respiratory_rate_summary.csv
   sleep.csv
   active_minutes.csv
   active_zone_minutes.csv
   time_in_heart_rate_zones.csv
   exercise.csv
   steps.csv
   EOF
   ```

   - PhysioNet can be slow (we saw ~15 KB/s), and `steps.csv` is last because it's the largest.
     `caffeinate -i` keeps a Mac awake; drop it on Windows or Linux.
   - If the download stops, run the same command again: `-c` resumes partial files. Don't add
     `-N`: it skips partial files whose date looks current.

5. **Check the files** against PhysioNet's checksums. Every line should say `OK`:

   ```bash
   cd data/raw/mcphases
   for f in *.csv; do
     h=$(shasum -a 256 "$f" | cut -d' ' -f1)
     if grep -qi "$h" SHA256SUMS.txt; then echo "OK      $f"; else echo "FAILED  $f"; fi
   done
   cd - >/dev/null
   ```

   For a `FAILED` file, run step 4 again with only that file in the list.

6. **Explore** with `notebooks/mcphases_eda.ipynb`, which prints aggregates only. Share only those
   aggregates, never rows or one participant's values.

### Which files and why

| File | Used for |
|---|---|
| `hormones_and_selfreport` | Phase labels (ground truth), hormones, and self-report that mirrors our check-in |
| `computed_temperature` | Nightly skin-temperature deviation, the main cycle signal |
| `resting_heart_rate`, `heart_rate_variability_details`, `respiratory_rate_summary` | Overnight signals that match the Google Health API |
| `sleep` | Main-sleep flag (which night a value belongs to) and minutes asleep |
| `subject-info` | Describing the cohort (how well results carry over to our users) |
| `steps`, `active_minutes`, `exercise` | Activity: a confounder for the phase model (exercise moves RHR) and activity-by-phase features |
| `active_zone_minutes`, `time_in_heart_rate_zones` | Optional activity detail |

**Not downloaded on purpose:**
- `wrist_temperature`: minute-level readings that include daytime and off-wrist time; `computed_temperature` covers it.
- `estimated_oxygen_variation`: a raw light ratio, not SpO2 %, so nothing in the API to match it.
- `sleep_score`: the Google Health API doesn't return a sleep score.
- `height_and_weight`: one value per study round, so it can't show cycle changes.
- `calories`, `distance`, `heart_rate`, `altitude`, `glucose`, `stress_score`, `demographic_vo2_max`:
  not needed. `distance` is mostly derived from steps; `heart_rate` is huge and daily RHR covers it.
