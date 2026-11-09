# Decisions

Newest at the bottom. One entry per decision. To change a decided item, add a new entry and point to the old one.

---

### D1. Three layers plus app, organized by architecture
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:** `signals/`, `rag/`, `agent/` and `app/`, each self-contained. Anyone can work on any layer.
- **Why:** The layers can be built in parallel, and the split matches how the system is graded and demoed.
- **Alternatives:** Organize by feature or by person (folders become stale when work shifts).

### D2. Contract-first with stubs
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:** Handoffs are Pydantic models in `contracts/` (`extra="forbid"`, versioned) with JSON fixtures. Every layer ships a stub on day one.
- **Why:** The walking skeleton works before any layer is real, and contract drift fails tests instead of the demo.
- **Alternatives:** Shared docs only (drift); JSON Schema files (more tooling).

### D3. Contract v0.1 refinements over the timeline draft
- **Date:** 2026-10-24 · **Status:** proposed, flexible. Expected to change as data access becomes clear (Google Health API fields, mcPHASES schema, check-in fields from D5).
- **Decision:**
  - Wearable fields are optional (None = missing), and units appear in field names.
  - Add `user_id`, `schema_version` and `CheckIn.bc_taken`.
  - `range_days` becomes `ovulation_window{start,end}`. Phase gets `"unknown"`, plus `method` and `source`.
  - `Evidence` gets `doc_id`/`chunk_id`.
  - `AgentResponse` gets `mode`, a required `uncertainty_note`, an optional `escalation` (required on red_flag), `fallback_used`, and structured `DataChip`s.
- **Why:** Missing data must be representable, the citation eval needs chunk ids, and "± days" was ambiguous.
- **Alternatives:** Keep the timeline shapes verbatim.

### D4. The uncertainty range is a feature
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:** Every estimate carries a window and a confidence. When signal is weak, show it wide or say "not enough data yet".
- **Why:** Fitbit signals may be too noisy for a point estimate, and the course rewards honest uncertainty.
- **Alternatives:** Point estimate only.

### D5. Red-flag detection and routing
- **Date:** 2026-10-24 · **Status:** open (needs more team discussion)
- **Why it matters:**
  - Missing a real red flag is the worst failure this app can have.
  - Unsafe outputs and diagnosis language are named red flags in the grading.
  - The approach decides what the check-in must collect, so it affects the contracts.
- **Starting point (from the timeline):** rules first, LLM second, plus a banned-phrases check on outputs ("you have…", "you are ovulating").
- **Approaches to weigh:**
  - Rules on structured check-in fields (exact and testable, but needs fields like "soaking hourly?").
  - The LLM extracts facts from chat and coded rules decide (handles paraphrase and negation; the decision stays traceable).
  - Keyword matching (simple, but brittle; best kept as a safety net when the LLM is down).
- **Also open:** the rule list itself (draft it from ACOG/MedlinePlus with citations), what "caution" vs "red_flag" means, and whether the LLM can ever lower a rule hit (proposal: never).
- **Deadlines:** decide the check-in fields before the Oct 28 contract lock if possible. The router is built Nov 16–19.

### D6. Graceful fallback on every external dependency
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:** If the Fitbit API fails, use cached data. If the LLM fails, use canned cited answers. If wearable signal is missing, use the calendar-count estimator. Each fallback is visible to the user (`fallback_used`).
- **Why:** A happy-path-only demo is a named red flag.

### D7. Agent has two modes: education and summary
- **Date:** 2026-10-24 · **Status:** decided; routing method open
- **Decision:**
  - **Education** answers general questions from the trusted corpus, with citations.
  - **Summary** is a conversational agent over the user's own data: weekly synthesis and "what's going on with me".
  - Both share safety checks and return `AgentResponse`.
- **Why:** Personal-data synthesis and general education need different grounding and different prompts.
- **Open:**
  - How a question is routed (user toggle, classifier, or LLM tool choice). The stub uses a toggle.
  - Whether to build a clinician summary. This would be a one-page handout to bring to an appointment: period dates and cycle lengths, symptom and check-in trends, wearable patterns, BC use, any flags raised, and suggested questions. It would be generated from the data (not free LLM text) and labeled real or synthetic with a "not a diagnosis" note. It would be offered on escalation (`Escalation.summary_pdf`) and on request.
  - Options: a downloadable PDF, an on-screen/copyable summary only, or cut.

### D8. LLM provider: OpenAI, a personal key per person
- **Date:** 2026-10-24 · **Status:** decided (model name open)
- **Why:** Everyone already has access.

### D9. App framework: Streamlit
- **Date:** 2026-10-24 · **Status:** decided
- **Why:** The whole team writes Python, it's fast to build, and it has a built-in test harness (`AppTest`).
- **Alternatives:** Gradio; FastAPI + web frontend (more flexible Cycle Clock, more work).

### D10. Environment: venv + requirements.txt
- **Date:** 2026-10-24 · **Status:** decided
- **Why:** It needs no extra tools, so anyone can clone and run.
- **Alternatives:** uv, conda, poetry.

### D11. mcPHASES stays local and never reaches an LLM
- **Date:** 2026-10-24 · **Status:** superseded by D18
- **Decision:** Only credentialed people handle the raw data. It stays on their machine in `data/raw/`, and only aggregate metrics are shared.
- **Why:** PhysioNet credentialed-access terms.

### D12. Embeddings + vector store
- **Date:** 2026-10-24 · **Status:** open
- **Notes:** The corpus is small (30 to 50 docs). A local option also works offline at the demo.

### D13. Storage for check-ins and cached data
- **Date:** 2026-10-24 · **Status:** open
- **Options:** SQLite; JSON files.

### D14. What user data is sent to the LLM
- **Date:** 2026-10-24 · **Status:** open
- **Proposal:** Send derived features and summaries, not raw Fitbit JSON, and only after the user opts in.

### D15. Phase model approach
- **Date:** 2026-10-24 · **Status:** open
- **Options:** Rules (temperature shift / RHR rise over baseline), or ML trained on mcPHASES. Either way, the calendar count is the fallback.

### D16. v1 scope cuts from the whiteboard
- **Date:** 2026-10-24 · **Status:** open
- **Candidates for stretch/out of scope:** sleep-stage model, activity suggestions, young-adult slider triggers, guideline→action-plan matching, FHIR export (PDF only).

### D17. Gate date changes
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:**
  - Integration #1 moves from Fri Nov 20 to **Thu Nov 19**.
  - The Week 13 integration checkpoint and mock demo is **Fri Dec 4**.
- **Why:** Nov 20 is the Quiz 2 class day. Dec 4 is confirmed on the course site, and that class includes teams red-teaming each other's agents, so our safety red-team set doubles as prep.

### D18. mcPHASES handling under the restricted-access DUA (supersedes D11)
- **Date:** 2026-10-26 · **Status:** decided
- **Decision:**
  - Each person gets their own PhysioNet access. No passing files around.
  - Raw data stays on that person's machine in `data/raw/mcphases/`.
  - No raw rows go to any third-party LLM API, coding assistants included. Claude writes the analysis
    code, a person runs it, and only schema and aggregates (counts, % missing, summary stats) are shared.
  - Public outputs (poster, demo, writeup) show aggregates or synthetic data, never one participant's series.
  - Never try to identify anyone; report anything that looks identifying to PHI-report@physionet.org.
- **Why:** mcPHASES is under PhysioNet's restricted-access DUA (D11 wrongly said credentialed access).
  The DUA requires "reasonable and prudent care" for electronic security and no sharing of access.
  Keeping raw rows away from LLM APIs is our own conservative reading, not an explicit DUA clause.
- **Scope:** Teammates' own Fitbit data is real personal data but is not under the DUA. Claude may read
  it locally (`data/raw/fitbit/`); it is never committed and is labeled `source="real"`.

### D19. Enforcing D18 in tooling; notebooks via nbstripout
- **Date:** 2026-10-26 · **Status:** decided
- **Decision:**
  - `.claude/settings.json` denies Claude reading `data/raw/mcphases/`, `notebooks/mcphases*`, `.env`
    and credential files. A PreToolUse hook (`.claude/hooks/block_mcphases.py`) blocks Bash commands that
    mention the same paths. Both are checked in, so every teammate's session gets them.
  - EDA may use notebooks. mcPHASES logic lives in importable functions that return aggregates only; the
    notebook calls them and Claude never reads it.
  - New dev dependency `nbstripout`: run `nbstripout --install` once per clone; CI fails on committed
    notebook outputs.
- **Why:** A rule that is only remembered is easy to break. Notebook outputs can carry real rows.
- **Limits:** The hook catches accidents, not deliberate workarounds. It also blocks harmless commands
  that merely mention those paths (e.g. a grep over docs); use the file tools for those.

### D20. Google Health API client and raw-pull caching
- **Date:** 2026-10-26 · **Status:** decided
- **Decision:**
  - Access goes through the course OAuth helper (BINF 4070 Lab 3): each person puts their own
    `GOOGLE_HEALTH_REFRESH_TOKEN` / `GOOGLE_HEALTH_HELPER_TOKEN` in `.env`. The course app is read-only.
  - `signals/google_health.py` is the client. Raw responses are saved to `data/raw/fitbit/`
    (gitignored, `source: real`) so we can re-analyze without new calls; this is the start of the
    cached-data fallback (D6).
  - New dependencies: `requests` (HTTP), `python-dotenv` (load `.env`), `ipykernel` (dev, run notebooks).
- **Why:** Same flow the course supports. Caching cuts API calls and gives the demo a fallback.
- **Known from the docs:** period dates have no read scope (only `reproductive_health.writeonly`), so
  cycle day 1 must come from our own check-in (relevant to D5). Temperature arrives as nightly +
  baseline Celsius (`daily-sleep-temperature-derivations`); `DailyRecord.skin_temp_dev_c` would be
  derived. Which types the course scopes cover is checked by the test pull.

### D21. mcPHASES EDA: aggregates-only code, suppression rules, pandas
- **Date:** 2026-10-27 · **Status:** decided
- **Decision:**
  - `signals/explore/mcphases_eda.py` returns aggregates only: counts, % missing, 1st–99th
    percentiles (never min/max, which are one person's values), and distributions *across*
    participants (never a per-participant list). A person runs it via the mcPHASES notebook.
  - Categories seen in fewer than 5 participants are shown as `<5`. Columns with more than 15
    distinct values are treated as free text: only the count of distinct values is shown.
  - Demographics (`subject-info.csv`) are reported because our users (young women) differ from the
    mcPHASES cohort, so fit needs to be shown. One column at a time (never crossed), binned
    (age band, menarche band), plus ethnicity and menstrual-health literacy. `income` and
    `sexually_active` are not reported.
  - New dependency: `pandas`.
- **Why:** 42 participants is small enough that rare categories, extremes, or crossed columns
  could single someone out (D18).
- **Out of scope for now:** `estimated_oxygen_variation.csv` is a raw infrared/red ratio, not SpO2
  percent, so it doesn't line up with the Google Health API.

### D22. EDA lives in notebooks/; the guardrail covers only the mcPHASES notebook file (amends D19, D21)
- **Date:** 2026-10-27 · **Status:** decided
- **Decision:**
  - EDA sits together in `notebooks/`: each notebook plus a `.py` of the same name that holds its
    code (`notebooks/mcphases_eda.py`). The mcPHASES loader that later work reuses is
    `signals/mcphases.py`.
  - The deny rule and Bash hook cover only the mcPHASES `.ipynb`, not the `.py` next to it. Only a
    notebook can carry outputs (data); the `.py` holds code, so Claude can read, edit and test it.
    Running it on the data stays blocked (the hook still stops `python ... mcphases`).
  - Claude Code refuses to let Claude edit its own `.claude/settings.json`, so a person makes
    changes to the deny rules.
- **Why:** One folder for exploration, as the team prefers, while the analysis code stays
  reviewable and covered by the leak tests.

### D23. The mcPHASES EDA is one self-contained notebook (amends D22)
- **Date:** 2026-10-27 · **Status:** decided
- **Decision:** The EDA helpers and sections live in the notebook itself (helpers at the top) and
  print plain-text tables, which are easier to read and paste back than JSON. The separate
  `notebooks/mcphases_eda.py` and its leak tests are removed. The reusable loader stays in
  `signals/mcphases.py` (with a test).
- **Trade-off:** Claude can't read or edit the notebook (D19), so its code isn't covered by tests.
  It was dry-run on synthetic tables with planted ids, extremes, free text and skipped columns
  before hand-off, and none appeared in the output. Later fixes are pasted in by a person.

### D24. Which mcPHASES files we use
- **Date:** 2026-10-27 · **Status:** decided
- **Decision:** Download and use `hormones_and_selfreport`, `subject-info`, `computed_temperature`,
  `resting_heart_rate`, `heart_rate_variability_details`, `respiratory_rate_summary`, `sleep`,
  `steps`, `active_minutes`, `exercise`, and optionally `active_zone_minutes` and
  `time_in_heart_rate_zones`. Everything else is left out. The list, reasons, and download steps
  are in `data/README.md`.
- **Why:** Each file either matches something the Google Health API returns or teaches a pattern
  the product needs (labels, symptoms by phase, activity as a confounder and for activity-by-phase
  features). Holding less restricted data is also safer under the DUA.
- **Left out:** `wrist_temperature` (all-day minute data incl. off-wrist; `computed_temperature`
  covers it), `estimated_oxygen_variation` (not SpO2 %), `sleep_score` (the API returns no sleep
  score), `height_and_weight` (one value per round, can't show cycle changes), `distance` (derived
  from steps), `heart_rate` (huge; daily RHR covers it), `calories`, `altitude`, `glucose`,
  `stress_score`, `demographic_vo2_max`.

### D25. Contract changes suggested by mcPHASES (for the Oct 28 contract discussion)
- **Date:** 2026-10-27 · **Status:** proposed
- **Proposals** (details in the mapping table at the end of `docs/data.md`):
  - **Phase labels:** mcPHASES uses `Fertility` (a fertile window from Mira's algorithm), not
    ovulation. Map it to `ovulatory`, or rename that value. Either way, the UI should describe
    patterns, and must not read as contraception advice ("safe days", "fertile today").
  - **`hrv_rmssd_ms`** = nightly mean of the 5-minute RMSSD samples, computed the same way for
    mcPHASES and the API, so a model trained on one carries over.
  - **`skin_temp_dev_c`** = nightly mean deviation from baseline (`computed_temperature`), which
    should match the API's nightly minus baseline.
  - **`CheckIn.bleeding`**: map mcPHASES' 8 flow levels onto our 5 values.
  - **`CheckIn.pain`**: our 0–10 scale vs mcPHASES' 6 text levels for cramps. Rescale, or adopt
    the 6 levels so check-ins and training data match.
  - **Respiratory rate**: available in both sources; candidate field for v0.2.
- **Also for the team:** the cohort is 18–29 with nobody under 18. If Inkling targets teens, say
  the data doesn't cover them. `flow_color` values (grey, yellow, orange) may matter for the
  red-flag list (D5).

### D26. Trusted-source whitelist for the RAG corpus
- **Date:** 2026-11-02 · **Status:** decided
- **Decision:** Store only US government pages (OWH, NICHD, MedlinePlus health topics, CDC, FDA),
  open-access papers (CC BY / CC BY-NC) about the cycle or the app's signals, and Google Health API
  docs (CC BY) for how signals are measured. Details and exclusions in [sources.md](sources.md).
- **Why:** Answers quote sources verbatim, so we can only store text we're allowed to reuse.
  Government sites are thin on wearable physiology, so papers fill that gap.
- **Alternatives:** Clinic sites and ACOG (copyrighted; link-only later), NHS (UK guidance).

### D27. RAG answer scope
- **Date:** 2026-11-02 · **Status:** decided
- **Decision:**
  - Topics: the cycle and the signals the app shows. Other wellness questions are declined.
  - Interpret, don't coach: explain signals and her data; don't tell her what to do.
  - Cycle-forward signal answers: start from her cycle, say when the timing doesn't fit, name other
    explanations (stress, sleep, getting sick) with equal weight, and don't pick a cause.
  - Patterns from her own history are fine with "might" and the amount of data stated. Never
    forecast a temperature shift.
  - No fertility timing (D25): no "safe days" or best days to try.
- **Why:** Keeps Inkling a cycle app, avoids overclaiming (D4), and stays on the right side of D25.
  Each rule becomes a key point in the eval (`evals/rag/README.md`).

### D28. Confidence is shown in words until it's validated
- **Date:** 2026-11-02 · **Status:** proposed
- **Decision:** The UI shows the likely window, a word (Low / Medium / Higher), coverage ("2 of 3 nights
  recorded") and a limit line ("Accuracy not validated yet"). It shows no number and no filling bar.
  `PhaseEstimate.confidence` stays in the contract and drives the word.
- **Why:** HCI lecture (slides-08 p.27): use numeric confidence only when its meaning and reliability
  are validated for that output. Coverage describes what arrived, not correctness (p.26). A bar reads
  as a measurement, and we have no calibration results before Sprint 2.
- **Revisit:** after the held-out calibration eval (Nov 21–25). If the range is calibrated, say so.
- **Alternatives:** Keep the Lab 8 bar (over-reliance risk, p.46); remove the word and show only the window.
