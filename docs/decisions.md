# Decisions

How this log works:
- One entry per decision, newest at the bottom. Numbers never change.
- **Open** items are updated in place. To change a **decided** item, add a new entry that points to the old one.
- Status words: **decided** · **proposed** (waiting for the team) · **open** (not settled) ·
  **team choice** (options listed, team picks) · **history** (done, kept for the record).

## Index

| # | Topic | Status | In one line |
|---|---|---|---|
| D1 | Layers | decided | signals, rag, agent, app. Each self-contained |
| D2 | Contracts + stubs | decided | Pydantic handoffs with fixtures. Every layer ships a stub |
| D3 | Contract v0.1 changes | history | Now in `contracts/models.py` |
| D4 | Uncertainty | decided | Every estimate has a window and a confidence |
| D5 | Red flags | proposed / open | Rules before the LLM. Rule list still open |
| D6 | Fallbacks | decided | Every outside dependency has a visible fallback |
| D7 | Agent modes | decided | Education and summary. Routing in D30 |
| D8 | LLM provider | decided | OpenAI. Model still open |
| D9 | App framework | decided | Streamlit |
| D10 | Environment | decided | venv + requirements.txt |
| D11 | (merged) | | Merged into D18 |
| D12 | Retrieval method | decided | BM25 for the demo and showcase. Hybrid only if time after freeze |
| D13 | Storage | decided | SQLite, owned by signals |
| D14 | Data sent to the LLM | decided | Opt-in context card of computed facts |
| D15 | Phase model | decided | Rules anchored on check-ins, then an ML model (planned) |
| D16 | v1 scope cuts | open | Candidates for stretch or out of scope |
| D17 | Gate dates | decided | Integration #1 Thu Nov 19. Mock demo Fri Dec 4 |
| D18 | mcPHASES handling | decided | Own access, local only, aggregates only, never to an LLM |
| D19 | Guardrails + EDA notebook | decided | Deny rules, Bash hook, nbstripout, one EDA notebook |
| D20 | Google Health client | decided | Course OAuth, raw pulls cached |
| D21 | EDA privacy rules | decided | Aggregates only. Small groups suppressed |
| D22 | (merged) | | Merged into D19 |
| D23 | (merged) | | Merged into D19 |
| D24 | mcPHASES files | decided | Which files we download, and why |
| D25 | Contract changes from mcPHASES | decided | Phase labels, HRV, temp, bleeding and pain mapping |
| D26 | Source whitelist | decided | US government pages, open-access papers, Google Health docs |
| D27 | Answer scope | decided | Cycle + app signals. Interpret, don't coach. No fertility timing |
| D28 | Confidence in words | decided | A word + coverage + a limit line. No number |
| D29 | Red-flag rule list v1 | proposed | Annika, on the `red-flag-router` branch (not merged yet). See `docs/safety_rules.md` there |
| D30 | Question pipeline | decided | One fixed pipeline, one LLM call |
| D31 | Output checks | decided | Code checks at runtime. LLM judge only in the offline eval |
| D32 | Trends tab | decided | Her data lined up by cycle day |
| D33 | Escalation + contracts v0.2 | decided | On-screen clinician summary. New response fields |
| D34 | Ovulation dates and the likely window | decided | Ovulation only looks back. A next-period window is the likely window |
| D35 | Birth control method | decided | Asked at onboarding, editable in settings, kept with start dates |
| D36 | Hero question | decided (for now) | "My period is late again and I'm exhausted", asked by synthetic Maya |

---

### D1. Three layers plus app
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:** `signals/`, `rag/`, `agent/` and `app/`, each self-contained. Anyone can work on any layer.
- **Why:** Layers can be built in parallel. The split matches how the system is graded and demoed.
- **Considered:** Folders by feature or by person (they go stale when work shifts).

### D2. Contract-first with stubs
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:** Handoffs are Pydantic models in `contracts/` (`extra="forbid"`, versioned) with JSON
  fixtures. Every layer ships a stub on day one.
- **Why:** The walking skeleton works before any layer is real. Contract drift fails tests, not the demo.
- **Considered:** Shared docs only (drift). JSON Schema files (more tooling).

### D3. Contract v0.1 changes over the timeline draft
- **Date:** 2026-10-24 · **Status:** history (now in `contracts/models.py`)
- Optional wearable fields with units in their names. `user_id`, `schema_version`, `CheckIn.bc_taken`.
  `ovulation_window` instead of "± days". An `unknown` phase. Chunk ids on `Evidence`. A structured
  `AgentResponse` (mode, uncertainty note, escalation, `fallback_used`, data chips).

### D4. The uncertainty range is a feature
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:** Every estimate has a window and a confidence. Weak signal → a wide window, or "not enough data yet".
- **Why:** Fitbit signals may be too noisy for a point estimate. The course rewards honest uncertainty.

### D5. Red flags: rules before the LLM
- **Date:** 2026-10-24, updated 2026-11-16 · **Status:** placement proposed (pending team). Rule list open.
- **Why it matters:**
  - Missing a real red flag is the worst failure this app can have.
  - Unsafe outputs and diagnosis language are named red flags in the grading.
  - The approach decides what the check-in must collect.
- **Proposal (2026-11-16):**
  - Rules run in three places: on check-in save, over her stored history (e.g. 90+ days without a
    period, 8+ days of bleeding), and on each chat message.
  - Rule hit → a template escalation. No LLM call, so it works with the LLM down.
  - The LLM can add caution. It can never clear a hit. No LLM "double-check" of a red flag.
  - Unclear or negated message ("I'm not soaking…") → a yes/no chip. Negation never cancels a hit on its own.
  - Follow-up questions only when needed ("soaking a pad every hour?" only when Bleeding = Heavy).
    No new daily questions.
  - Banned phrases in answers ("you have…", "you are ovulating") are checked in D31.
- **Rule list:** proposed in D29 (Annika, `red-flag-router` branch, not merged yet), with an
  extractor that pulls facts and code rules that decide. Same approach as above.
- **Still open:** agreeing on that list. What "caution" vs "red_flag" means.
- **Stretch:** the LLM pulls facts from chat, and the same code rules decide. It can only add a hit.
- **Measured by:** the red-team set (recall and false alarms).
- **Considered:** keyword matching alone (brittle). Check-in rules alone (misses chat).

### D6. Graceful fallback on every outside dependency
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:**
  - Fitbit API fails → cached data.
  - LLM fails → canned cited answers.
  - No wearable signal → calendar count.
  - Every fallback is visible to the user (`fallback_used`).
- **Why:** A happy-path-only demo is a named red flag.

### D7. Agent has two modes: education and summary
- **Date:** 2026-10-24 · **Status:** decided
- **Decision:**
  - **Education:** general questions, answered from the trusted corpus with citations.
  - **Summary:** her own data ("what's going on with me", weekly synthesis).
  - Both share safety checks and return `AgentResponse`.
- **Why:** Her data and general education need different grounding and prompts.
- **Routing:** proposed in D30 (one pipeline, mode taken from what the answer cites).
- **Clinician summary:** proposed in D33.

### D8. LLM provider: OpenAI, a personal key per person
- **Date:** 2026-10-24 · **Status:** decided. Model name still open.
- **Why:** Everyone already has access.

### D9. App framework: Streamlit
- **Date:** 2026-10-24 · **Status:** decided
- **Why:** The whole team writes Python. It's fast to build and has a test harness (`AppTest`).
- **Considered:** Gradio. FastAPI + a web frontend (more flexible Cycle Clock, more work).

### D10. Environment: venv + requirements.txt
- **Date:** 2026-10-24 · **Status:** decided. No extra tools, so anyone can clone and run.

### D12. Retrieval method
- **Date:** 2026-10-24, updated 2026-11-16, decided 2026-11-22 (team) · **Status:** decided.
- **Decision:** A (BM25) for the Dec 4 mock demo and the showcase. Try C (hybrid) only if there's
  time after feature freeze, measured on the dev set.
- **Why:** BM25 is measured (Hit@5 0.83 on dev), offline and deterministic, which matters for a live
  demo with a planned failure. Embeddings would add a model pick and a network dependency 11 days
  before freeze.
- **How it was compared:** compare on the dev set (Hit@5, capped Recall@5). Never on test.
- **A. Keyword (BM25, current)**
  - Pros: already works (Hit@5 0.83 on dev). Local, offline, free, same result every run. No new
    dependency. Matches exact medical terms. Easy to debug.
  - Cons: misses everyday wording, synonyms and typos. Capped Recall@5 is 0.34.
- **B. Embeddings**
  - Pros: matches meaning. Common approach. May find more relevant docs.
  - Cons: needs a model pick. An API model needs the network for every question (a local model is a
    new dependency). The index is rebuilt when the corpus or model changes. Harder to debug. Not yet
    measured on our set.
- **C. Hybrid (both, rankings merged)**
  - Pros: both kinds of match. BM25 still works if embeddings are down.
  - Cons: most moving parts. Merging needs tuning. Needs B's model pick too.
- **Any option:** "I don't know" = a retrieval-score cutoff tuned on the dev IDK items + an LLM decline.
- **Note:** the corpus is small (60 docs). A local option also works offline at the demo.

### D13. Storage: SQLite owned by signals
- **Date:** 2026-10-24, updated 2026-11-16, decided 2026-11-22 (team) · **Status:** decided.
- **Decision:**
  - One SQLite file under `data/` (gitignored), via Python's built-in `sqlite3`. No new dependency.
  - Holds check-ins and parsed `DailyRecord`s.
  - Raw Fitbit JSON stays in the D20 file cache: used to re-parse, and as the API-down fallback.
  - New functions: `save_checkin(...)` and `sync(user_id)`.
- **Why:** Saving by date and pulling date ranges is simple. History rules (D5) and Trends (D32) need it.
- **Considered:** JSON files (easy to read, awkward to update and query).

### D14. What reaches the LLM: a context card
- **Date:** 2026-10-24, updated 2026-11-16, decided 2026-11-22 (team) · **Status:** decided.
- **Decision:**
  - Opt-in ("Use my data in answers", off by default). Off → education answers only.
  - The LLM gets a card of facts computed in code, each with an id. Fixed menu: now (phase, cycle day,
    confidence word, coverage), recent nights vs her usual, this cycle vs her last 1–3, and up to 6
    past cycle and period lengths.
  - Each fact says how much data it's based on.
  - Never on the card: raw JSON, names or ids, correlations, a future fertile window (D25),
    temperature-shift forecasts (D27).
  - Answers cite fact ids. Cited facts become "From your data" chips.
- **Why:** Code computes and the LLM narrates, so numbers can't be made up and are checkable (D31).
  Less of her data leaves the machine.
- **Considered:** raw or lightly processed records (more to leak, and the LLM does the math).
- **Example card:** see `docs/architecture.md`, section 6.

### D15. Phase estimate v1: rules anchored on check-ins, then an ML model
- **Date:** 2026-10-24, updated 2026-11-16, decided 2026-11-22 (team) · **Status:** decided.
- **Decision:**
  - Offline: mcPHASES tunes and tests the rules. Output: a few aggregate numbers + a calibration
    table (safe to commit under D18).
  - Runtime: `estimate_phase` runs on demand over stored records. No batch jobs.
  - Rules: a temperature shift or RHR rise over her own baseline (`signals/detector.py`, PR #11).
  - Cycle day 1 = a period start from her check-ins. Calendar count is the fallback (PR #9).
  - Needed: logging a past period, or "last period start" at onboarding.
  - **ML model: a planned goal, not a stretch** (Grace, 2026-11-22). Train on mcPHASES, evaluate on
    held-out participants with the same split as the rules (`evals/signals/run.py`), and ship it
    only if it beats the rules there.
- **Why:** Rules first: realistic for the Nov 19 gate and easy to explain. The ML model is a planned
  goal (decided 2026-11-22); it ships only if it beats the rules on held-out participants.
- **Before shipping the ML model:** weights trained on restricted data are a grey area under the
  DUA (D18). Check with the team or instructor whether trained weights may be committed and used in
  the app; if not, keep it as an offline result for the poster and writeup.
- **Stretch:** per-user numbers updated each cycle, tested by replaying mcPHASES cycle by cycle.

### D16. v1 scope cuts from the whiteboard
- **Date:** 2026-10-24 · **Status:** open
- **Candidates for stretch or out of scope:** sleep-stage model, activity suggestions, young-adult
  slider triggers, guideline → action-plan matching, FHIR export (PDF only).

### D17. Gate date changes
- **Date:** 2026-10-24 · **Status:** decided. Integration #1 moved to Thu Nov 19 (Nov 20 is Quiz 2).
  Mock demo is Fri Dec 4, when teams red-team each other's agents. Dates live in `docs/timeline.md`.

### D18. mcPHASES handling under the restricted-access DUA
- **Date:** 2026-10-26 · **Status:** decided (replaces D11, which wrongly said "credentialed access")
- **Decision:**
  - Everyone gets their own PhysioNet access. No passing files around.
  - Raw data stays on that person's machine in `data/raw/mcphases/`.
  - No raw rows go to any LLM API, coding assistants included. Claude writes the analysis code, a
    person runs it, and only schema and aggregates come back (counts, % missing, summary stats).
  - Public outputs (poster, demo, writeup) show aggregates or synthetic data. Never one participant's series.
  - Never try to identify anyone. Report anything that looks identifying to PHI-report@physionet.org.
- **Why:** The DUA requires "reasonable and prudent care" and no sharing of access. Keeping rows away
  from LLM APIs is our own cautious reading, not an explicit DUA clause.
- **Scope:** Teammates' own Fitbit data is real personal data but not under the DUA. Claude may read
  it locally (`data/raw/fitbit/`). It is never committed and is labeled `source="real"`.

### D19. Guardrails and the mcPHASES EDA notebook (merges D22, D23)
- **Date:** 2026-10-26, merged 2026-11-17 · **Status:** decided
- **Decision:**
  - `.claude/settings.json` blocks Claude from reading `data/raw/mcphases/`, the mcPHASES notebook
    (`notebooks/mcphases*.ipynb`), `.env` and credential files.
  - A Bash hook (`.claude/hooks/block_mcphases.py`) blocks commands that touch the same paths, or
    that run mcPHASES analysis.
  - Both are checked in, so every teammate's session gets them. Only a person can change the deny
    rules (Claude can't edit its own settings).
  - EDA lives in `notebooks/`. The mcPHASES EDA is one self-contained notebook (helpers at the top,
    plain-text tables). Claude can't read it, so a person pastes in fixes. It was dry-run on synthetic
    tables before hand-off.
  - The reusable loader is `signals/mcphases.py`, with a test.
  - `nbstripout`: run `nbstripout --install` once per clone. CI fails on committed notebook outputs.
- **Why:** A rule that is only remembered is easy to break. Notebook outputs can carry real rows.
- **Limits:** The hook catches accidents, not deliberate workarounds. It also blocks harmless commands
  that only mention those paths (use the file tools for those).

### D20. Google Health API client and raw-pull caching
- **Date:** 2026-10-26 · **Status:** decided
- **Decision:**
  - Access goes through the course OAuth helper (BINF 4070 Lab 3). Each person puts their own tokens
    in `.env`. The course app is read-only.
  - `signals/google_health.py` is the client. Raw responses are saved to `data/raw/fitbit/`
    (gitignored, `source: real`) for re-analysis and as the cached-data fallback (D6).
  - New dependencies: `requests`, `python-dotenv`, `ipykernel` (dev).
- **Why:** The flow the course supports. Caching cuts API calls and gives the demo a fallback.
- **Known:** period dates can't be read (write-only), so cycle day 1 must come from our own check-in.
  Temperature arrives as nightly + baseline, so `skin_temp_dev_c` is nightly minus baseline.

### D21. mcPHASES EDA privacy rules
- **Date:** 2026-10-27 · **Status:** decided
- **Decision:**
  - The EDA returns aggregates only: counts, % missing, 1st–99th percentiles (never min or max, which
    are one person's values), and distributions across participants (never a per-participant list).
  - Categories seen in fewer than 5 participants show as `<5`. Columns with more than 15 distinct
    values count as free text: only the number of distinct values is shown.
  - Demographics (`subject-info.csv`): one column at a time, never crossed, binned. `income` and
    `sexually_active` are not reported.
  - New dependency: `pandas`.
- **Why:** 42 participants is small enough that rare categories, extremes or crossed columns could
  single someone out (D18). Demographics are shown because our users differ from the cohort.
- **Out of scope:** `estimated_oxygen_variation.csv` is a raw sensor ratio, not SpO2 %.

### D24. Which mcPHASES files we use
- **Date:** 2026-10-27 · **Status:** decided
- **Use:** `hormones_and_selfreport`, `subject-info`, `computed_temperature`, `resting_heart_rate`,
  `heart_rate_variability_details`, `respiratory_rate_summary`, `sleep`, `steps`, `active_minutes`,
  `exercise`. Optional: `active_zone_minutes`, `time_in_heart_rate_zones`. Details in `data/README.md`.
- **Why:** Each file matches something the Google Health API returns, or teaches a pattern the
  product needs. Holding less restricted data is also safer under the DUA.
- **Left out:** `wrist_temperature` (covered by `computed_temperature`), `estimated_oxygen_variation`
  (not SpO2 %), `sleep_score` (the API has none), `height_and_weight`, `distance`, `heart_rate` (huge,
  daily RHR covers it), `calories`, `altitude`, `glucose`, `stress_score`, `demographic_vo2_max`.

### D25. Contract changes suggested by mcPHASES
- **Date:** 2026-10-27, decided 2026-11-22 (team) · **Status:** decided. Details in the mapping table at the end of `docs/data.md`.
- **Decisions:**
  - **Phase labels:** mcPHASES uses `Fertility` (a fertile window from Mira's algorithm), not
    ovulation. Map it to `ovulatory`, or rename that value. The UI must never read as contraception
    advice ("safe days", "fertile today").
  - **`hrv_rmssd_ms`:** nightly mean of the 5-minute RMSSD samples, computed the same way for both
    sources, so a model trained on one carries over.
  - **`skin_temp_dev_c`:** nightly mean deviation from baseline. Should match the API's nightly minus baseline.
  - **`CheckIn.bleeding`:** map mcPHASES' 8 flow levels onto our 5.
  - **`CheckIn.pain`:** our 0–10 vs mcPHASES' 6 text levels for cramps. Rescale, or adopt the 6 levels.
  - **Respiratory rate:** in both sources. Candidate field for v0.2.
- **Also:** the cohort is 18–29, nobody under 18. If Inkling targets teens, say the data doesn't cover
  them. `flow_color` values (grey, yellow, orange) may matter for the red-flag list (D5).

### D26. Trusted-source whitelist for the RAG corpus
- **Date:** 2026-11-02 · **Status:** decided
- **Decision:** Store only US government pages (OWH, NICHD, MedlinePlus, CDC, FDA), open-access papers
  (CC BY / CC BY-NC) about the cycle or the app's signals, and Google Health API docs (CC BY).
  Details and exclusions in [sources.md](sources.md).
- **Why:** Answers quote sources word for word, so we only store text we may reuse. Government sites
  are thin on wearables, so papers fill that gap.
- **Considered:** Clinic sites and ACOG (copyrighted, link-only later). NHS (UK guidance).

### D27. Answer scope
- **Date:** 2026-11-02 · **Status:** decided
- **Decision:**
  - Topics: the cycle and the signals the app shows. Other wellness questions are declined.
  - Interpret, don't coach: explain signals and her data. Don't tell her what to do.
  - Signal answers start from her cycle. Say when the timing doesn't fit. Name other explanations
    (stress, sleep, getting sick) with equal weight. Don't pick a cause.
  - Patterns from her history are fine with "might" and the amount of data stated. Never forecast a
    temperature shift.
  - No fertility timing (D25): no "safe days", no best days to try.
- **Why:** Keeps Inkling a cycle app, avoids overclaiming (D4), and respects D25. Each rule is a key
  point in the eval (`evals/rag/README.md`).

### D28. Confidence is shown in words until it's validated
- **Date:** 2026-11-02, decided 2026-11-22 (team) · **Status:** decided.
- **Decision:** The UI shows the likely window, a word (Low / Medium / Higher), coverage ("2 of 3
  nights recorded") and a limit line ("Accuracy not validated yet"). No number, no filling bar.
  `PhaseEstimate.confidence` stays in the contract and drives the word.
- **Why:** HCI lecture (slides-08 p.27): show a number only when its meaning is validated. Coverage
  describes what arrived, not correctness (p.26). A bar reads as a measurement.
- **Revisit:** after the held-out calibration eval (Nov 21–25). D34 makes the likely window a
  next-period window.
- **Considered:** the Lab 8 bar (over-reliance risk, p.46). Only the window, no word.

### D30. One fixed question pipeline, no router
- **Date:** 2026-11-16, decided 2026-11-22 (team) · **Status:** decided.
- **Decision:**
  - Every question: red-flag rules → fertility rule → context card (if opted in) → retrieve (always)
    → one LLM call returning JSON → output checks (D31) → regenerate once → safe fallback.
  - `mode` comes from what the answer cites: education, summary or both. The user toggle goes away.
  - The last 1–2 chat turns are passed for follow-ups. Chat is session-only in v1.
- **Why:** No routing errors to evaluate. Mixed questions work naturally. One call. Safety checks run
  on the same path every time.
- **Considered:** a separate classifier call (extra delay, a new error type). Tool calling (results
  vary run to run, harder to test and guard).
- **Stretch:** rewrite the question before retrieval. Keep only if dev Hit@5 improves.
- **Open:** chat memory across visits (touches D13, D14).

### D31. Output checks
- **Date:** 2026-11-16, decided 2026-11-22 (team) · **Status:** decided.
- **Decision:** Option 1 (code checks) at runtime. An LLM judge is used only in the offline answer
  eval.
- **Why:** Runtime stays deterministic and works with the LLM down (D6), and the offline judge still
  gives a meaning-level groundedness score for the poster and writeup. A judge on every answer means
  an LLM outage hits twice, and judge errors trigger more fallbacks.
- **Both options (as compared):** fail → regenerate once → safe fallback. Checks can only make answers stricter.
  The eval is graded by a different model or by hand, so it isn't circular.
- **Option 1: code checks only.** Banned phrases (diagnosis, fertility timing) in the answer and its
  cited snippets. Every cited chunk was retrieved. Every cited fact is on the card. Every number in
  the answer appears in a cited fact. A decline makes no claims. The uncertainty note is there.
  - Pros: no extra API call. Same result every run, easy to unit-test. Works with the LLM down. Clear
    why it failed.
  - Cons: only catches what's written as a rule. Can't tell if a sentence is backed by its snippet.
    Phrase lists need upkeep. Can wrongly flag quoted source text.
- **Option 2: Option 1 + an LLM judge** (yes/no: backed by the cited text? diagnosis? fertility
  timing? coaching? optionally: declined although relevant chunks were retrieved?)
  - Pros: checks meaning (paraphrase, groundedness, coaching tone). One prompt covers many rules.
    Closer to what the answer eval measures.
  - Cons: an extra LLM call per answer. Results vary run to run. A judge error counts as a fail, so an
    LLM outage hits twice. A same-model judge may share blind spots. Wrong fails → more fallbacks.

### D32. A cycle-aligned Trends tab
- **Date:** 2026-11-16, decided 2026-11-22 (team) · **Status:** decided.
- **Decision:** Default view: this cycle vs previous ones, by cycle day, with check-in markers.
  By-date view with phase bands (the default for new users). Trends and the agent use the same
  signals function (`CycleHistory`), so the chart and the chat agree.
- **Why:** Fitbit already shows metrics by date. It can't line them up by cycle day, because it can't
  read period dates. That view is Inkling's own.
- **Considered:** a Fitbit-style metrics tab by date (duplicates Fitbit).

### D33. Escalation details and contracts v0.2
- **Date:** 2026-11-16, decided 2026-11-22 (team) · **Status:** decided.
- **Escalation:** clinician summary on screen and copyable, built from her data with no LLM (PDF is a
  stretch). Nearby care = fixed links (NPI Registry lookup is a stretch).
- **Contracts v0.2** (separate PR: models + fixtures + `SCHEMA_VERSION` together):
  - `AgentResponse.response_type`: answer, decline or escalate. Escalate always means `safety = "red_flag"`.
  - `AgentResponse.decline_reason`: out_of_scope, no_sources, not_enough_data, fertility_timing, no_consent.
  - `mode`: education, summary or both.
  - New `CycleHistory` contract. New functions `save_checkin` and `sync`.
- **Open:** `CheckIn` red-flag fields (D5). An optional, labeled `general_tips` slot for the
  coaching-tips idea (not decided).

### D34. Ovulation dates look back only; a next-period window is the likely window
- **Date:** 2026-11-20, decided 2026-11-22 (team) · **Status:** decided. Updates D28's "likely window".
- **Decision:**
  - All four phases stay, `ovulatory` included. "You're in your ovulatory phase" describes today.
  - **No future ovulation dates.** `ovulation_window` is filled only when all its days are past, i.e.
    after her next period starts ("ovulation likely happened Oct 17–19"). Roughly 11–14 days before
    that period from the calendar now; the wearable method (temperature rise) can tighten it later.
  - **New `next_period_window`:** last period start + her usual cycle length, widened by how much
    her cycles vary (mcPHASES spread 27–32 days until she has 2 cycles). This is the "likely window"
    on the Today card and the cycle clock (D28), with the confidence word.
  - **Drop `ovulation_est_date`:** a single date overstates the precision. The window carries it.
- **Why:**
  - A future ovulation window works as a fertile-window calendar, which D25 and D27 rule out. A past
    one explains her signals (temperature and RHR rise after ovulation) without being plannable.
  - The calendar can't place ovulation before it happens: a typical person's cycle varies about
    3 days (mcPHASES), but the time from ovulation to the next period is steadier (fertile window
    ends 9–12 days before it in the middle half of cycles).
  - A next-period window keeps D4/D28's "show a range, not a number" on something safe and useful.
- **Considered:**
  - Keep a future ovulation window: works as a fertile-window calendar (D25/D27), and it's the least
    reliable estimate.
  - Remove the ovulation fields, keep a next-period window: simplest safe option, but the app can't
    say when ovulation likely happened when explaining her temperature or heart-rate patterns.
  - Look-back only, no next-period window: smallest change, but the Today card usually has no range
    to show (weakens D28) and users get no "when's my next period".
- **Changes (one contracts PR):** `PhaseEstimate` gets `next_period_window`, loses
  `ovulation_est_date`; `OvulationWindow` becomes a general `DateWindow`. Fixture + `SCHEMA_VERSION`.
  Signals computes both windows. App: shows "Next period likely …" (the Today card is already
  driven by the phase, PR #12). Agent: describes a look-back window only as past.

### D35. Birth control method, asked at onboarding and editable in settings
- **Date:** 2026-11-20, decided 2026-11-22 (team) · **Status:** decided. Touches D5 (check-in questions).
- **Decision:**
  - Onboarding asks "Which birth control do you use, if any?". Settings lets her change it when she
    starts, stops or switches.
  - Stored as a history: each method with the date it started. Cycles before a start still count
    as natural cycles; cycles after it don't.
  - Options: none · combined pill · patch · ring · progestin-only pill · shot · implant ·
    hormonal IUD · copper IUD · condoms or other barrier · other / prefer not to say.
  - Signals: phase `unknown` on combined methods, shot, implant and hormonal IUD; "uncertain"
    (`unknown` for now) on the progestin-only pill; phases as normal on copper IUD, barrier or none.
    Period tracking works on all of them.
  - Red flags (D29): the 90+ days rule gets a birth control exception. Missed periods are an
    expected effect of the shot, implant, IUDs and extended pill use (OWH).
- **Why:** Most hormonal methods stop ovulation, and the bleed in a pill break is a withdrawal bleed,
  not a period (CDC US SPR, OWH). On combined pills, HRV and resting heart rate follow the pill pack
  (pmid-34367655). `CheckIn.bc_taken` ("taken today", yes/no) can't tell these apart and doesn't fit
  methods that aren't taken daily. Research summary: `docs/data.md`, "Periods from check-ins".
- **Interim (on `signals`):** `bc_taken=True` in the last 35 days makes the phase `unknown`.
- **Considered:** keep `bc_taken` only (can't tell methods apart). Ask daily (more questions than needed).
- **Open:** where the history lives in the contracts (a new profile model, or a `CheckIn` field).
  The corpus doesn't say which IUDs and implants stop ovulation: the RAG corpus needs CDC US SPR
  pages for those before answers can rely on it.

### D36. Hero question: "My period is late again and I'm exhausted"
- **Date:** 2026-11-22 · **Status:** decided (for now). Revisit if the demo story changes.
- **Decision:** The demo is built around synthetic Maya asking "My period is late again and I'm
  exhausted." Maya (20, hard-to-predict periods, wears a Fitbit) has 4 finished cycles of 27–36 days
  and a current cycle running past her usual (`signals/synthetic.py`, PR #12).
- **Why:** It exercises every layer at once: cycle history (late vs her usual), wearable signals
  (temperature, sleep), check-ins (fatigue), cited education, and the red-flag rules (a few days
  late is not a red flag; 90+ days without a period is).
- **Follow-up:** the calendar estimate calls a cycle "later than usual" only after usual + 7 days, so
  at Maya's day 34 (usual ~31) it shows "likely luteal". A soft "past your usual" flag on `signals`
  would let the app and agent say she's late.
- **Open:** the persona's source. `signals/synthetic.py` cites PRODUCT.md, which isn't in the repo yet.
