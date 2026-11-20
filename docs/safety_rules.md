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
| Soaking a pad/tampon every 1-2 hours, or passing clots bigger than a quarter | [OWH: Your menstrual cycle](https://www.womenshealth.gov/menstrual-cycle/your-menstrual-cycle) (verbatim); [CDC: About heavy menstrual bleeding](https://www.cdc.gov/female-blood-disorders/about/heavy-menstrual-bleeding.html) |
| Rash + vomiting/diarrhea + dizziness or fainting together, especially during tampon use — ask about fever but don't require a number to act on this combination | [FDA: The facts on tampons and tampon safety](https://www.fda.gov/consumers/consumer-updates/facts-tampons-and-how-use-them-safely) |
| A sunburn-like **rash alone**, during or soon after tampon use, with no other sign yet | Same FDA page: each TSS sign (fever, rash, vomiting, diarrhea, fainting/dizziness) is listed as independently actionable — "if you have **any** of these symptoms... seek medical attention immediately," not a required combination. A lone rash with no tampon mentioned isn't enough on its own. |
| Feels feverish with no other TSS sign yet, and no self-reported temperature | Not enough to judge (D4) — ask if they've taken their temperature before answering. |
| A self-reported temperature ≥100.4°F | 100.4°F is the commonly-used general fever threshold, but **not sourced to any document in `rag/manifest.csv`** — it's general medical knowledge, not a corpus citation. FDA's TSS-specific sign (verified, same page as above) is ≥102°F. **Not** inferred from overnight wearable skin-temp deviation — that's a relative, cycle-baseline signal, not a same-day illness check. |
| Fainting, severe dizziness, or feeling like passing out during a period | [OWH: Your menstrual cycle](https://www.womenshealth.gov/menstrual-cycle/your-menstrual-cycle); CDC heavy-bleeding page |
| No period for 90+ days, not pregnant/breastfeeding/in perimenopause | [OWH: Your menstrual cycle](https://www.womenshealth.gov/menstrual-cycle/your-menstrual-cycle) — **verbatim**: "if you don't have a period for 90 days (three months)... talk to your doctor." NICHD's own amenorrhea page gives a *stricter* 6-month / 3-periods-in-a-row threshold, so OWH is the better citation for this exact number. |
| Severe pelvic/abdominal pain that stops normal activity and isn't relieved by OTC pain relief | [OWH: Period problems](https://www.womenshealth.gov/menstrual-cycle/period-problems); MedlinePlus: Period pain (possible endometriosis, torsion, or ectopic — needs a clinician, not chat) |
| Heavy or persistent bleeding between periods, or any bleeding after menopause | [OWH: Period problems](https://www.womenshealth.gov/menstrual-cycle/period-problems) |

## `caution` — flag + suggest a clinician, keep answering

| Condition | Source |
|---|---|
| Cycles outside the usual 24-38 day range, or irregular for a few months | [OWH: Your menstrual cycle](https://www.womenshealth.gov/menstrual-cycle/your-menstrual-cycle) states 24-38 days as the normal range **verbatim** — not the commonly-quoted 21-35, which is looser than what our actual source says. The OWH/NICHD PCOS pages list "irregular periods" as a symptom but give no cycle-length number of their own. |
| New discharge with a different color, texture, or odor, no fever/severe pain | [CDC: Bacterial vaginosis](https://www.cdc.gov/bacterial-vaginosis/about/index.html); [NICHD: vaginitis symptoms](https://www.nichd.nih.gov/health/topics/vaginitis/conditioninfo/symptoms) |
| Missed 2+ combined pills in a row | [CDC US SPR: combined hormonal contraceptives](https://www.cdc.gov/contraception/hcp/usspr/combined-hormonal-contraceptives.html). **Unverified**: the specific missed-pills flowchart doc this originally cited (`stacks.cdc.gov/view/cdc/251909`) was dropped from `rag/manifest.csv` in a later cleanup; nobody has confirmed this replacement page actually contains the same 2+ missed-pill guidance. |
| Mood/sleep/energy changes that disrupt daily life beyond the usual PMS window | OWH: Premenstrual dysphoric disorder (PMDD) |

## `none`

Everything else: typical 24–38 day variation, usual PMS, cramps relieved by OTC meds, normal
spotting, brown (oxidized) blood.

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

## Verification pass (2026-11-16)

Went back and fetched the actual source text for the heavier-traffic citations instead of trusting
the conversational draft. Found and fixed four real gaps, reflected in the tables above:

1. **Amenorrhea citation was attributed to the wrong document.** NICHD's amenorrhea page actually
   defines secondary amenorrhea as 6 months / 3 periods in a row, not 90 days. OWH's own menstrual
   cycle page is the one that states "90 days (three months)" verbatim — that's the citation to use.
2. **The TSS rule under-triggered.** FDA's page lists each sign (fever, rash, vomiting, diarrhea,
   fainting/dizziness) as independently sufficient to act on, not a required three-way combination.
   Added a lone-rash-with-tampon-use trigger, and decoupled a reported temperature number from
   needing "feverish" wording too.
3. **The PCOS/irregular-cycle threshold (35+ days) wasn't grounded in any corpus document**, and
   contradicted OWH's own stated normal range (24-38 days) — 35 is inside that range. Fixed to
   reference 24-38, and noted the extractor only matches descriptive phrases, not parsed numbers.
4. **The missed-pills citation points to a document that no longer exists** in `rag/manifest.csv`
   (dropped in a later cleanup). Re-pointed to the closest surviving CDC US SPR page, flagged
   unverified since nobody's confirmed it still carries the 2+ missed-pill guidance.

Not fully resolved: the 100.4°F general fever threshold still isn't tied to any corpus document.
This was a spot-check of the highest-traffic rules, not an exhaustive re-verification of every
citation — still worth a second pass before calling D29 decided.
