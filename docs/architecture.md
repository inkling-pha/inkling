# Architecture

> **Status: v0.2 draft for team review, not final.**
> - Reworked from Grace's diagram on 2026-11-16. Matching decisions: D5, D12–D15 (updated) and D30–D33 (new). D29 is Annika's red-flag rule list in [decisions.md](decisions.md).
> - **Proposed**: Grace agreed, team hasn't reviewed yet. **Team choice**: options, no recommendation.
>   **Stretch**: only with spare time, or if an eval calls for it. **Open**: not settled.
> - Before building on an unsettled part, raise it at standup or in an issue. Record the outcome in
>   decisions.md, then update this page.

**Diagram:** [Inkling architecture v0.2 in Lucid](https://lucid.app/lucidchart/5624e4ef-72bd-4c26-9a83-e1253fd7e566/edit). If it doesn't open, ask Grace for access.

In short:
- Same four layers.
- Rules decide safety before any LLM call.
- Every question goes through one fixed pipeline.
- Two choices are left to the team: output checks and retrieval method.

## At a glance

| # | Topic | Proposal | Status | Decision |
|---|---|---|---|---|
| 1 | Offline vs runtime | Build and evaluate offline. Run on demand at app load | Proposed | D15 |
| 2 | Phase estimate v1 | Rules over her baseline, anchored on check-in period starts. Calendar fallback | Proposed | D15 |
| 3 | Storage | SQLite (built into Python), owned by signals. Raw Fitbit JSON stays in the file cache | Proposed | D13 |
| 4 | Answering a question | One fixed pipeline, one LLM call. No router, no tool calling | Proposed | D30 |
| 5 | Red flags | Rules before the LLM. Rule list still open | Proposed / Open | D5 |
| 6 | What reaches the LLM | Opt-in context card of facts computed in code | Proposed | D14 |
| 7 | Output checks | Option 1 code checks, or Option 2 code checks + LLM judge | Team choice | D31 |
| 8 | Retrieval method | A BM25, B embeddings, C hybrid | Team choice | D12 |
| 9 | App | New Trends tab. Changes to Check-in and Ask | Proposed | D32 |
| 10 | Fallbacks | One per dependency. Red flags never need the LLM | Proposed | D6 |
| 11 | Escalation | On-screen clinician summary, fixed care links | Proposed (briefly discussed) | D33 |
| 12 | Contracts v0.2 | `response_type`, `decline_reason`, `CycleHistory` (separate PR) | Proposed | D33 |

## 1–3. Data side

Built offline from mcPHASES. Runs on her own data each time the app loads.

**Offline (build and evaluate)**
- mcPHASES tunes and tests the phase rules.
- Output: a few aggregate numbers + a calibration table. Safe to commit under D18.
- Evals: signals (held-out mcPHASES), rag (56 questions), agent (Q&As + red-team set).
- The test split never feeds back. Few-shot examples come from dev only.
- mcPHASES never reaches an LLM (D18).

**Runtime (each app load, no batch jobs)**
- Sync Fitbit → save → estimate phase → build cycle history.
- Answer questions (section 4).

**Phase estimate v1**
- Rules: a temperature shift or RHR rise over her own baseline.
- Cycle day 1 = a period start from her check-ins. The API can't read period dates.
- No wearable data → calendar count (built on `signals`, PR #9).
- To build: log a past period, or ask "when did your last period start?" at onboarding. Without it, phase = `unknown`.
- Ovulation dates only look back; the likely window is a next-period window (D34).
- Birth control method from onboarding/settings decides whether phases apply (D35).
- *Stretch:* ML model. Only if it beats the rules on held-out participants.
- *Stretch:* per-user numbers updated each cycle (cycle length, shift size). Test by replaying mcPHASES cycle by cycle.

**Storage**
- SQLite, built into Python (`sqlite3`). No new dependency.
- Owned by signals. Holds check-ins and parsed `DailyRecord`s. The file lives under `data/` (gitignored).
- Raw Fitbit JSON stays in `data/raw/fitbit/` (D20). Used to re-parse, and as the fallback when the API is down.
- New functions: `save_checkin(user_id, date, checkin)` and `sync(user_id)`. `sync` pulls missing days and reports when it last synced, live or cached.
- Synthetic Maya loads the same way, labeled `synthetic`.

## 4. Answering a question

One fixed pipeline, one LLM call. No classifier, no tool calling. Question types (her data,
education, both) come from what the answer cites, so nothing has to route them.

1. **Red-flag rules** (section 5). Hit → template escalation, stop.
2. **Fertility rule** (D25). Hit → decline, stop.
3. **Context card** (section 6). Only if she opted in.
4. **Retrieve** from the trusted corpus. Always.
5. **One LLM call** → JSON: answer or decline, cited chunk ids, cited fact ids.
6. **Output checks** (section 7). Fail → regenerate once → safe fallback.
7. **Mode** = what was cited: `education`, `summary` or `both`. The user toggle goes away.

- Follow-ups: the last 1–2 chat turns are passed along.
- *Stretch:* rewrite the question before retrieval (+1 LLM call). Keep only if dev Hit@5 improves.

## 5. Red flags: rules before the LLM

- Rules decide.
- The LLM can add caution. It can never clear a rule hit.
- No LLM "double-check" of a red flag. That check could only un-flag.

| Where rules run | How |
|---|---|
| Check-in save | "Soaking a pad or tampon every hour?" Shown only when Bleeding = Heavy. Pain = Severe also counts. Banner on Check-in and Today, so she sees it without opening chat |
| Her history | Math on stored check-ins. Examples: 90+ days since the last period, 8+ days of bleeding in a row |
| Each message | Phrase patterns ("soaking through a pad", "clots the size of", "passed out"). Tuned to catch everything. Worded "if you're soaking…" |

- Unclear or negated message ("bleeding a lot", "I'm not soaking…") → a yes/no chip. Yes → escalate. Negation never cancels a hit on its own.
- No new daily questions. A longer check-in gets skipped, and missed period starts hurt the estimate.
- Rare flags (fainting, fever with pain) → caught by message patterns.
- The banner stays for the session. Works with the LLM down.
- **Rule list:** proposed in D29 (Annika, `red-flag-router` branch, not merged yet). Check-in fields still open (D5).
- *Stretch:* the LLM pulls facts from chat, and the same code rules decide. It can only add a hit.
- Measured by the red-team set: recall and false alarms, negated phrasings included.

## 6. What reaches the LLM

Code computes, the LLM narrates.
- Opt-in: "Use my data in answers", off by default.
- Off → education answers only.
- On → the LLM gets a **context card**: short facts computed from her data, each with an id. Never raw data.

**What's on the card** (a fixed menu)
- Now: phase, cycle day, confidence word, coverage.
- Recent nights vs her usual: skin temp, RHR, HRV, sleep.
- This cycle vs her last 1–3: same cycle days, cycle length, check-in symptoms.
- History: up to 6 past cycle and period lengths.

**Never on the card:** raw JSON, names or ids, correlations, a future fertile window (D25),
temperature-shift forecasts (D27).

**Example card** (synthetic user, as it would appear in the prompt)

```text
CONTEXT CARD · source: synthetic · as of 2026-11-17
Computed by Inkling. Cite facts by id. Don't calculate new numbers.
"Usual" = her median over the last 30 nights.

[f1]  Phase: likely luteal · cycle day 22 · confidence: Medium · method: wearable
[f2]  Coverage: 6 of the last 7 nights recorded
[f3]  Cycle day 1: 2026-10-27, from her check-in
[f4]  Skin temp: +0.3 °C above her usual · 3 of the last 3 nights
[f5]  Resting HR: 63 bpm vs usual 60 (+3) · 5-night average
[f6]  HRV: 41 ms vs usual 47 (-6) · 5-night average
[f7]  Sleep: 6 h 40 min a night vs usual 7 h 15 min · last 7 nights
[f8]  Resting HR, cycle days 15-22: +3 bpm this cycle · +2 and +3 in the last 2 cycles
[f9]  Cycle lengths: 29, 31, 28 days · last 3 cycles
[f10] Period lengths: 5, 5, 6 days · last 3 periods
[f11] Fatigue logged: 3 of the last 5 days (cycle days 18-22)
[f12] Fatigue logged, same days last cycle: 2 of 5
[f13] Cramps logged: 0 of the last 5 days
[f14] Birth control: none (from settings, D35)
```

How an answer uses it, for "Why am I so tired this week?":

> Your temperature has been higher than your usual for 3 nights [f4], and your resting heart rate
> is up a little [f5]. That pattern is common in the second half of the cycle, where you likely are
> now (day 22, medium confidence) [f1] [source]. Shorter sleep could also explain the tiredness:
> about 35 minutes less a night than usual [f7]. You logged fatigue on 3 of the last 5 days, similar
> to last cycle [f11] [f12].

- Each fact says how much data it's based on.
- The answer cites fact ids like chunk ids. Cited facts become "From your data" chips.
- A question that needs a fact not on the menu → decline with `not_enough_data`. These declines show what to add next.

## 7. Team choice: output checks

Pick one. Both options:
- Regenerate once on a fail, then show a safe fallback.
- Can only make answers stricter.
- Grade the eval with a different model or by hand, so it isn't circular.

**Option 1: code checks only**
- No banned phrases (diagnosis, fertility timing) in the answer or its cited snippets
- Every cited chunk was actually retrieved
- Every cited fact is on the card
- Every number in the answer appears in a cited fact
- A decline makes no claims
- The uncertainty note is there

**Option 2: Option 1 + an LLM judge** (yes/no questions)
- Is each claim backed by the cited text?
- Diagnosis? Fertility timing? Coaching?
- Optional: declined even though relevant chunks were retrieved?

| | Option 1: code checks | Option 2: + LLM judge |
|---|---|---|
| Pros | No extra API call (no added delay or cost) · Same result every run, easy to unit-test · Works when the LLM is down · Clear why it failed | Checks meaning: paraphrase, groundedness, coaching tone · One prompt covers many rules · Closer to what the answer eval measures |
| Cons | Only catches what's written as a rule · Can't tell if a sentence is backed by its snippet · Phrase lists need upkeep · Can wrongly flag quoted source text | Extra LLM call per answer · Results vary run to run, harder to test · A judge error counts as a fail, so an LLM outage hits twice · A same-model judge may share blind spots · Wrong fails → more fallbacks |

## 8. Team choice: retrieval method

Pick one.
- BM25 stays for the Nov 19 integration either way.
- All three are RAG. Only how chunks are found differs.
- Compare on the dev set (Hit@5, capped Recall@5). Never on test.
- Any option: "I don't know" = a retrieval-score cutoff (tuned on dev) + an LLM decline.

| | A. Keyword (BM25, current) | B. Embeddings | C. Hybrid (both, rankings merged) |
|---|---|---|---|
| Pros | Already works: Hit@5 0.83 on dev (target 0.8) · Local, offline, free, same result every run · No new dependency or model pick · Matches exact medical terms well · Easy to debug | Matches meaning: everyday wording, synonyms, typos · Common approach · May find more relevant docs | Gets both kinds of match · BM25 still works if embeddings are down |
| Cons | Misses everyday wording, synonyms, typos · Capped Recall@5 is 0.34 | Needs a model pick (D12) · An API model needs the network for every question. A local model = new dependency · Rebuild the index when the corpus or model changes · Harder to see why a chunk matched · Not yet measured on our set | Most moving parts · Merging needs tuning · Needs B's model pick too |

## 9. App

New Trends tab: her data lined up by cycle day. Fitbit can't do this, because it can't read period dates.

| Tab | Now | Proposed |
|---|---|---|
| Nav | Today · Check-in · Ask | Today · Check-in · **Trends** · Ask |
| Today | Cycle Clock · summary card · "last N nights" | Same + "See trends" · Dial uses her average cycle length (replaces `DEFAULT_DIAL_DAYS`) · No period logged → "Phase unclear · Log your last period" |
| Check-in | Lost when the session ends | Saved · Log a past date or last period start · Red-flag question only when needed · Rules run on save → banner |
| Trends (new) | none | Default: this cycle vs previous ones, by cycle day, with check-in markers · By-date view with phase bands (default for new users) · Same data function as the agent (`CycleHistory`), so chart and chat agree |
| Ask (chatbot) | "General / My own data" toggle · stub answers | Toggle removed → one-time data opt-in · Answer: text + "From your data" chips + "From trusted sources" chips + uncertainty note · Decline card with a next step · Red flag: escalation card + session banner · Fallback labeled "what our sources say" |
| Header | Fixed SYNTHETIC DATA badge | Badge follows each view's `source`: real, synthetic or mixed |

**Declines say why, and what would help**

| `decline_reason` | What she sees |
|---|---|
| `no_sources` | "Our sources don't cover this, so I won't guess. Worth asking a clinician." |
| `out_of_scope` | "Inkling covers your cycle and the signals it shows." + a redirect |
| `not_enough_data` | What's missing + a "Log a period" or "Check in" button |
| `fertility_timing` | "Inkling can't help time sex to get or avoid pregnancy. A clinician or family-planning service can." |
| `no_consent` | "Turn on 'Use my data in answers'." |

- The opt-in is about sending her data to the LLM.
- No wearable is a different case. Answers use check-ins only. Wearable questions → `not_enough_data`.

**Chat memory**
- v1: this session only, never saved. The last 1–2 turns are passed for follow-ups.
- **Open:** memory across visits (touches storage D13 and privacy D14).

## 10–11. Fallbacks and escalation

Every outside dependency has a visible fallback (D6). Red flags need none: they never call the LLM.

| Failure | Fallback (marked `fallback_used`) |
|---|---|
| Fitbit API down | Saved records + "last synced" date |
| No wearable data | Calendar count from check-ins |
| No period logged | Phase unknown + "log your last period" |
| LLM down or slow | "What our sources say": top snippets word for word (search runs locally) + a few canned demo answers |
| Red flag | Rules and templates only. No LLM |

**Escalation** (only briefly discussed)
- Clinician summary: on screen, copyable, built from her data. No LLM. *Stretch:* PDF.
- Nearby care: fixed links (campus health, health-center finders). *Stretch:* NPI Registry lookup.

## 12. Layers, entry points, contracts

All handoffs are Pydantic models in `contracts/models.py`. Example payloads are in `contracts/fixtures/`.

| Handoff | Contract | Entry point | v0.2 |
|---|---|---|---|
| app → signals | `CheckIn` | `save_checkin(user_id, date, checkin)` | **new** |
| app → signals | sync status | `sync(user_id)` | **new** |
| signals → agent, app | `DailyRecord`, `PhaseEstimate` | `get_daily_records(user_id)`, `estimate_phase(user_id)` | unchanged |
| signals → agent, app | `CycleHistory` | `cycle_history(user_id)` | **new contract** |
| rag → agent | `Evidence` | `retrieve(query, user_context) -> list[Evidence]` | unchanged |
| agent → app | `AgentResponse` | `respond(question, user_id, history)` | `mode` param removed |

**Contracts v0.2** (separate PR: models + fixtures + `SCHEMA_VERSION` + decisions entry together, per CLAUDE.md)
- `AgentResponse.response_type`: answer, decline or escalate. Escalate always means `safety = "red_flag"`.
- `AgentResponse.decline_reason`: the reasons in section 9.
- `mode`: education, summary or both. Matches the eval set.
- `PhaseEstimate`: add `next_period_window`, drop `ovulation_est_date`, `ovulation_window` past dates only (D34).
- Birth control method history (D35). Where it lives is open.
- **Open:** `CheckIn` red-flag fields. They wait on D5.
- **Open:** an optional, labeled `general_tips` slot for the coaching-tips idea. Hidden on caution or red flag. Not decided.

Every contract carries a `source` (real, synthetic or mixed) so the UI can label it.

| Layer | Owns |
|---|---|
| `signals/` | Google Health client + raw cache · parser · SQLite store · phase estimator · cycle history · mcPHASES loader |
| `rag/` | Corpus · retriever |
| `agent/` | Red-flag rules (the app also calls them on check-in save) · fertility rule · context card · LLM call · output checks · fallbacks |
| `app/` | Tabs · labels · opt-in · escalation view |

## Open items and stretch

| Kind | Items |
|---|---|
| Team choice | Output checks: Option 1 or 2 · Retrieval: A, B or C |
| Open | D5 red-flag rule list and check-in fields · D8 LLM model · D12 embedding model (B or C only) · D16 scope cuts · Chat memory across visits · Coaching-tips idea |
| Stretch | ML phase model · Per-user numbers · Query rewriting · LLM red-flag fact extraction · Decline review · Clinician summary PDF · NPI care lookup |

## Stubbed vs real

Update at each integration gate (Nov 15, Nov 19, Dec 4).

| Component | Status | Notes |
|---|---|---|
| Contracts + fixtures | real | v0.1. v0.2 proposed above |
| signals: records | real | Fitbit parsed into `DailyRecord` and stored (PR #8). Users with nothing stored get the fixture |
| signals: sync | real, not wired | `sync(user_id)` pulls new days (PR #9). The app doesn't call it yet |
| signals: phase estimate | real (calendar) | From logged periods; `unknown` without one (PR #9). Doesn't use the detector yet. Ovulation fields stay empty (D34) |
| signals: luteal-rise detector | real, not wired | `signals.detector`: temperature, RHR and HRV vs her own 28-day baseline, look-back only (D15, D34). Held-out eval in `evals/signals/run.py` (PR #11) |
| signals: mcPHASES records | real | `signals.mcphases_records`: cleaned `DailyRecord`s + phase labels for offline evals only (see docs/data.md) |
| signals: Google Health client | real | Pulls and caches raw Fitbit data |
| rag: retrieve | real, not wired | `rag.retriever`: BM25 over all 60 docs (1,314 chunks), real citations. The agent still uses `rag.stub` until the fertility guard (D25) exists |
| agent: respond | stub | Wires stubs. No LLM, no pipeline, no safety checks yet |
| app | partial | Today (Cycle Clock, source, coverage, limit), check-in with Undo, Ask, and failure/red-flag previews run on the stubs. Check-ins last one session (D13). Red-flag, sync and fallback states are demo previews until the router and fallbacks exist |
| evals: rag | partial | 56 questions, 32 dev references. `python -m evals.rag.run` gives Hit@5 and capped Recall@5. Answer metrics wait for generation (see `evals/rag/README.md`) |
| evals: signals | partial | `python -m evals.signals.run`: held-out balanced accuracy 0.64, 95% CI 0.55–0.73 (luteal vs not, Mira labels), coverage 0.61, median lag 2 days. Ovulation-day error and calibration not yet. See `evals/signals/README.md` |
| evals: agent | not started | Planned in the timeline's Sprint 2 |
| Storage | real, not wired | SQLite (D13), PRs #8–#9. The app doesn't save check-ins to it yet |
