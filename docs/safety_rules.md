# Safety rules (draft, D5)

**Proposed (D29), implemented, not yet decided by the full team.** Answers the timeline task
"Red-flag list from ACOG guidance, with citations (D5)" — sourced from D26's whitelist (CDC,
FDA, OWH, NICHD) instead of ACOG, which D26 excludes as copyrighted. Citations are to the
already-vetted sources in `rag/manifest.csv` / `docs/sources.md` (D26) where one exists there;
MedlinePlus period pain isn't in the RAG corpus (not yet added) but is cited here for the rule
itself, not for retrieval.

## Approach (D5's "also open" question)

**Recommendation:** the LLM extracts a few structured facts from the chat message or check-in
(bleeding amount, pad-soak rate, fever, fainting, pain severity, days since last period, pills
missed in a row), then **coded rules, not the LLM, decide the safety level** from those facts.
Keyword matching stays a fallback safety net only if the LLM is down (D6). The LLM never lowers a
rule hit (D5's proposal) — it can only fail to extract a fact, never override one.

Why: the eval questions (`evals/rag/questions/`) are free text ("i am bleeding so much more than
usual", "i almost passed out... feel feverish"), not taps on structured fields, so pure
structured-check-in rules (D5's first option) would miss most of them. This matches what Selina
described in chat: rules are hard-coded, but keyed off extracted facts rather than one big
scenario list.

**Contract gap this surfaces:** `CheckIn` (contracts/models.py) has no fields for fever, fainting,
pad-soak rate, or days-since-last-period — only `bleeding` (none/spot/light/medium/heavy),
`pain` (0–10), `energy`, `symptoms[]`, `bc_taken`. Either add fields, or treat these as
agent-layer-only facts extracted from chat and never logged to the check-in. Needs a team call.

## `red_flag` — pause, route to care (`Escalation` required)

| Condition | Source |
|---|---|
| Soaking a pad/tampon every hour for 2+ hours straight, or passing clots bigger than a quarter | [CDC: About heavy menstrual bleeding](https://www.cdc.gov/female-blood-disorders/about/heavy-menstrual-bleeding.html) |
| Sudden rash + vomiting/diarrhea + dizziness or fainting together, especially during tampon use — ask about fever but don't require a number to act on this combination | [FDA: The facts on tampons and tampon safety](https://www.fda.gov/consumers/consumer-updates/facts-tampons-and-how-use-them-safely) (toxic shock syndrome warning signs) |
| Feels feverish with no other TSS sign yet, and no self-reported temperature | Not enough to judge (D4) — ask if they've taken their temperature before answering; a self-report ≥100.4°F (CDC's general fever threshold) tightens the call. **Not** inferred from overnight wearable skin-temp deviation — that's a relative, cycle-baseline signal, not a same-day illness check. |
| Fainting, severe dizziness, or feeling like passing out during a period | [CDC: heavy menstrual bleeding](https://www.cdc.gov/female-blood-disorders/about/heavy-menstrual-bleeding.html); [OWH: Period problems](https://www.womenshealth.gov/menstrual-cycle/period-problems) |
| No period for 90+ days, not pregnant/breastfeeding/in perimenopause | [NICHD: Amenorrhea](https://www.nichd.nih.gov/health/topics/amenorrhea); OWH menstrual-cycle fact sheet |
| Severe pelvic/abdominal pain that stops normal activity and isn't relieved by OTC pain relief | [OWH: Period problems](https://www.womenshealth.gov/menstrual-cycle/period-problems); MedlinePlus: Period pain (possible endometriosis, torsion, or ectopic — needs a clinician, not chat) |
| Heavy or persistent bleeding between periods, or any bleeding after menopause | [OWH: Period problems](https://www.womenshealth.gov/menstrual-cycle/period-problems) |

## `caution` — flag + suggest a clinician, keep answering

| Condition | Source |
|---|---|
| Cycles persistently 35+ days apart, or irregular for 3+ months | [OWH: Polycystic ovary syndrome](https://www.womenshealth.gov/a-z-topics/polycystic-ovary-syndrome); [NICHD: PCOS](https://www.nichd.nih.gov/health/topics/pcos) |
| New discharge with a different color, texture, or odor, no fever/severe pain | [CDC: Bacterial vaginosis](https://www.cdc.gov/bacterial-vaginosis/about/index.html); [NICHD: vaginitis symptoms](https://www.nichd.nih.gov/health/topics/vaginitis/conditioninfo/symptoms) |
| Missed 2+ combined pills in a row | [CDC US SPR: missed combined pills flowchart](https://stacks.cdc.gov/view/cdc/251909) |
| Mood/sleep/energy changes that disrupt daily life beyond the usual PMS window | OWH: Premenstrual dysphoric disorder (PMDD) |

## `none`

Everything else: typical 21–35 day variation, usual PMS, cramps relieved by OTC meds, normal
spotting.

## Open for the team

- Exact thresholds: "90 days" (OWH) vs. ACOG's adolescent-specific guidance, which is stricter.
- ~~Does fever need a number, or just a yes/no the LLM extracts?~~ Resolved above: the TSS symptom
  combination fires `red_flag` without a number; a lone "feels feverish" asks for a self-report
  rather than guessing, and ≥100.4°F (CDC) tightens an already-feverish case.
- ~~Grey or brown period blood (eval q013/q014)~~ Resolved: brown is oxidized, older blood —
  `none` on its own. Grey is in D25's `flow_color` note (mcPHASES uses grey/yellow/orange) and
  folds into the existing discharge/BV `caution` rule above, not its own row.
- Confirm the extraction-then-rules approach above matches what Selina's already building before
  anyone starts coding `agent/`'s router.

v1 implemented in `agent/safety.py` (rules) and `agent/fertility_guard.py` (D25), wired through
`agent/router.py`. Fact extraction there is v1 keyword matching, the fallback-safety-net option
in D5 — swap for an LLM extractor once D14 (what reaches the LLM) is decided. Promoted to
`decisions.md` as **D29** (D28 was taken by the confidence-display decision).
