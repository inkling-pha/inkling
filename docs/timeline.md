# Timeline

**Source of truth for schedule and progress** (replaces the shared timeline doc).
- **This plan is flexible.** Anyone can move, add, split or drop tasks, or shift internal dates, as we learn more. Only the *(course deadline)* dates are fixed.
- Check a box when the work is merged to `main`.
- If a date moves, change it here and add a line to [decisions.md](decisions.md).
- Tasks are grouped by layer, not person. Anyone can pick up anything; mention what you're taking at standup.

## Key dates

- [x] **Sat Oct 24**: Kickoff
- [ ] **Wed Oct 28**: Contracts v0.1 agreed. They stay flexible: changes follow the contract-change rule in CLAUDE.md.
- [ ] **Fri Oct 30**: Week 8 design studio (storyboard, user flow, lo-fi prototype)
- [ ] **Tue Nov 3**: Timed slide dry run, hard stop at 5:00
- [ ] **Fri Nov 6**: Part 2 presentation, slides due by class *(course deadline)*
- [ ] **Wed Nov 11, 11:59 PM ET**: Part 2 written draft due *(course deadline)*
- [ ] **Sun Nov 15**: Walking skeleton works end to end
- [ ] **Thu Nov 19**: Integration #1 with all real components (moved off Quiz 2 day, see D17)
- [ ] **Wed Dec 2**: Feature freeze, bug fixes only after this
- [ ] **Fri Dec 4**: Integration checkpoint + mock demo *(course deadline)*
- [ ] **Wed Dec 9**: Poster printed
- [ ] **Fri Dec 11**: Showcase: 1-min pitch, poster, live demo *(course deadline)*
- [ ] **Wed Dec 16, 11:59 PM ET**: Technical writeup due, tentative *(course deadline)*

Other class dates: Quiz 2 on Fri Nov 20; no class on Fri Nov 27 (Thanksgiving).

---

## Part 2: Proposal (Oct 24 – Nov 11)

### Oct 24–25 · Kickoff
**Signals**
- [x] PhysioNet credentialing + CITI training
- [x] Claim the course Fitbit and start wearing it

**RAG**
- [x] Draft the trusted-source whitelist (org + why trusted) in [sources.md](sources.md)
- [x] Finalize the whitelist and log it in decisions.md (D26, D27)
- [x] List the questions users actually ask (54, split dev/test in `evals/rag/questions/`)

**Agent / Safety / App**
- [x] Repo + README
- [x] Task board (this file)
- [x] Draft interface contracts (v0.1 in `contracts/`)

### Oct 26–30 · Week 8 design studio
**All**
- [ ] Pick the hero question: the one question the demo is built around
- [ ] Agree on contracts v0.1, including the check-in fields (see D5) and the mcPHASES questions (see D25)

**Signals**
- [x] Test pull from the Google Health API: which fields come back (temperature? HRV?) and how often (see [data.md](data.md))
- [x] Check the mcPHASES schema (wearable signals, hormone and phase labels) and note mismatches with the contracts (see [data.md](data.md#mcphases), D24, D25)
- [ ] Sketch the Cycle Clock dial

**RAG**
- [x] Collect 30–50 source documents
- [ ] Pick embeddings + vector store (D12)
- [x] Define the RAG metrics

**Agent / Safety / App**
- [ ] Architecture diagram v1 (start from [architecture.md](architecture.md))
- [ ] Red-flag list from ACOG guidance, with citations (D5)
- [ ] Storyboard + lo-fi prototype for the studio

### Oct 31 – Nov 2 · Slides (5 min total)
**Signals**
- [ ] Problem + Maya (1 min)
- [ ] Data + access plan (1 min)
- [ ] Cycle Clock mock screenshot

**RAG**
- [ ] Evaluation plan + timeline (1 min)
- [ ] One retrieved answer with citations

**Agent / Safety / App**
- [ ] Architecture + interface (1.5 min)
- [ ] 1–2 feedback questions
- [ ] Assemble the deck in one visual style

Candidate feedback questions:
1. Is a wearable-based ovulation estimate with a visible uncertainty range trustworthy enough to lead the demo, or should education lead?
2. Besides held-out mcPHASES labels and classmate testing, how else should we check that red-flag escalation fires when it should?

### Nov 3–6 · Present
- [ ] Tue Nov 3: Timed dry run. Each section is presented by whoever built it.
- [ ] Nov 4–5: Fix dry-run issues, second run Thu, submit slides Thu night, pick a note-taker
- [ ] Fri Nov 6: Present. Log peer feedback the same day; anything that changes a plan goes in decisions.md.

### Nov 7–11 · Written draft (five parts)
- [ ] Problem
- [ ] Data plan
- [ ] Technical approach
- [ ] Evaluation (model, RAG and safety metrics)
- [ ] Timeline + risks
- [ ] Merge + edit pass Tue Nov 10, updated with peer feedback
- [ ] Submit by Wed Nov 11, 11:59 PM ET

---

## Part 3: Build & Demo (Nov 12 – Dec 16)

Build a thin end-to-end slice first, then make each layer real. A polished UI over hardcoded data is a named red flag.

### Nov 12–15 · Sprint 0: walking skeleton
**Signals**
- [ ] Synthetic Maya: 4 cycles of 27–36 days with matching RHR and temperature patterns (`data/synthetic/`)
- [x] Stub PhaseEstimate (`signals/stub.py`)
- [ ] mcPHASES → `DailyRecord`s: apply the cleaning rules in [data.md](data.md#cleaning) (one row per participant-day, 2024 RHR and steps excluded), after contracts v0.1 settle D25

**RAG**
- [ ] Index v0 (10 docs)
- [ ] `retrieve()` returning real citations

**Agent / Safety / App**
- [ ] App shell + check-in screen
- [ ] Agent loop calling the signals and RAG stubs with the LLM (the stub wiring exists; no LLM yet)
- [ ] Storage layer (D13)

**Gate, Sun Nov 15:** Maya asks the hero question and gets an answer with one evidence chip, end to end.

### Nov 16–19 · Sprint 1: make it real
**Signals**
- [ ] Baselines + temperature-shift / RHR-rise detector
- [ ] Phase model v1 on mcPHASES (D15)
- [ ] Cycle Clock with a narrowing range

**RAG**
- [ ] Full corpus indexed
- [ ] Citation-grounded answers
- [ ] Evidence chip UI
- [ ] Birth control content + missed-log follow-up

**Agent / Safety / App**
- [ ] Red-flag router v1 (D5)
- [ ] Education vs summary routing (D7)
- [ ] Clinician summary, if kept (D7)
- [ ] Live Fitbit sync in the app

RAG candidates (later, after the basic RAG works):
- Link-only "read more" sources (Mayo Clinic, Cleveland Clinic, ACOG, Google Health help center, non-open-license papers): shown as links, never stored or cited as evidence. Needs a contract change (e.g. a `read_more` list on `AgentResponse`, since `Evidence` requires a snippet).

UX candidates (not scheduled; raise at standup):
- Select-to-ask: tap a card or number and ask about it; the app passes the item as `user_context`, so the user doesn't type the referent.
- Clarifying chips: when a question is ambiguous (e.g. "my discharge is a weird color"), offer option buttons (colors, amounts) instead of a follow-up question. Could also feed red-flag rules (D5).
- Find care near me (`Escalation.nearby_care`): the user enters a ZIP code and we look up OB-GYNs via the public NPI Registry API (no key). Caveats: NPI addresses can be stale or billing-only, and it doesn't show insurance or whether they take new patients. Pair it with static links (campus health, health-center finders) and a cached fallback for the demo.

**Gate, Thu Nov 19:** Integration #1. All real components are wired, and what's still mocked is listed in architecture.md.

### Nov 21–25 · Sprint 2: evals (async, Thanksgiving week)
**Signals**
- [ ] Held-out participant eval: phase accuracy, ovulation-day error in days, calibration of the range
- [ ] Missing-data behavior

**RAG**
- [ ] RAG eval set (~40 Q&A)
- [ ] Groundedness + citation accuracy
- [ ] Out-of-scope questions get "I don't know"

**Agent / Safety / App**
- [ ] Safety red-team set (~50 prompts: red flags, diagnosis requests, teen/privacy cases)
- [ ] Escalation recall + false-alarm rate

### Nov 30 – Dec 2 · Harden
**Signals**
- [ ] Fall back to cached data if the Fitbit API fails
- [ ] Tune what the chart shows

**RAG**
- [ ] Fall back to canned cited answers if the LLM fails
- [ ] 5 classmate user tests (bonus)

**Agent / Safety / App**
- [ ] "Real vs synthetic" label on every data view
- [ ] Record a full fallback demo video
- [ ] Demo script

**Gate, Fri Dec 4:** Mock demo, run exactly like showcase day, including a live failure and the switch to fallback. Teams red-team each other's agents in this class.

### Dec 5–10 · Polish
**Signals**
- [ ] Poster: results charts
- [ ] Practice the 1-min lightning pitch

**RAG**
- [ ] Poster: user-test findings + RAG metrics
- [ ] Fix mock-demo feedback

**Agent / Safety / App**
- [ ] Poster: architecture diagram + safety stance
- [ ] Demo laptop setup + offline backup
- [ ] Print the poster by Wed Dec 9

**Fri Dec 11:** Showcase. Rotate who runs the station and who talks to visitors.

### Dec 12–16 · Writeup
- [ ] What we built: data + model
- [ ] What we built: RAG
- [ ] Results: model eval
- [ ] Results: RAG + user tests
- [ ] Safety + privacy stance
- [ ] What's next + who did what
- [ ] Individual reflections (one per person)
- [ ] Merge Tue Dec 15
- [ ] Submit by Wed Dec 16, 11:59 PM ET. Check that no claim goes beyond what the demo showed.

---

## Team rhythm
- **Standups:** Mon + Thu, 15 min: what shipped, what's blocked, which contract changed. Update this file at standup.
- **Definition of done:** see CLAUDE.md.
