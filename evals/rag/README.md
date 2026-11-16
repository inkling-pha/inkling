# RAG eval set

Questions for evaluating retrieval and cited answers. They were written from the user's side
(what someone would type into the app) **before** anyone looked at a source, so the set isn't
biased toward what the corpus happens to cover. A question is never dropped because the corpus
can't answer it: either a source is added or the expected answer becomes "I don't know".

- `questions/dev.jsonl`: guides source collection and tuning.
- `questions/test.jsonl`: held out. Nobody tunes prompts, chunking or retrieval against it.
- `references/` (added after collection): expected sources and key points per question.

## Reference fields

| Field | Values | Meaning |
|---|---|---|
| `id` | `q001`… | The question this answers. One row per question. |
| `expected_doc_ids` | list of manifest `doc_id`s | The docs the key points come from. Used for Hit@5 and Recall@5. |
| `acceptable_doc_ids` | list of manifest `doc_id`s | Other docs that cover the same content. Count for Hit@5 only. |
| `key_points` | list of strings | Facts a good answer covers, each with a source in the corpus. Used for coverage. |
| `behaviors` | list of strings | Things the answer must do or avoid ("doesn't diagnose"). Reported as a separate pass rate. |
| `expected_safety` | `none` / `caution` / `red_flag` | `caution`: "worth asking a clinician". `red_flag`: pause and route to care. |
| `idk_expected` | bool | `true`: the right answer is "I don't know" or a decline. |
| `notes` | string | Context and reviewer notes, not graded. Optional content goes here as "Optional, not graded: …"; points that need her logged data as "Agent eval, not graded here: …". |

Safety labels are provisional: `red_flag` follows the CLAUDE.md list for now and will be revised
once the evidence-based red-flag list (D5) exists.

## Question fields

| Field | Values | Meaning |
|---|---|---|
| `id` | `q001`… | Stable forever, never reused. |
| `question` | string | The user's wording, verbatim (typos included). |
| `context` | string or `null` | The scenario the app would supply (a tapped card, BC status, cycle day). |
| `mode` | `education` / `summary` / `both` | D7. RAG metrics skip `summary`; those items are for the agent eval. |
| `category` | see below | The topic. Used for coverage and to stratify the split. |
| `in_scope` | bool | `false`: Inkling should decline, redirect, or say "I don't know". |
| `group` | string or `null` | Near-twins (tuning on one is tuning on the other). A group never spans both files. |
| `added` | date | When the item was added. |

Categories: `cycle_basics`, `symptoms`, `late_irregular`, `bleeding_red_flags`, `birth_control`,
`pcos`, `wearable`, `clinician`, `exercise`, `weekly_review`, `out_of_scope`. `category` is
always the topic: a diagnosis request about PCOS is `pcos` with `in_scope: false`.
`out_of_scope` is for topics outside these areas (unrelated health, logistics, third parties,
fertility timing). Expected safety level goes in the references, not here.

## Split and freeze

Split once with a fixed seed (20261031), about 40% test, stratified by category. Two subtypes
were their own strata so each appears on both sides: fertility requests (avoid vs. trying to
conceive) and period color (brown vs. grey). Groups stay on one side.

Rules, from the `rag-questions-v1` tag on:
- No existing line in `questions/test.jsonl` changes, typo fixes included.
- New test items (teammates, classmates) are **appended** with a new id and today's `added` date.
- Sources are collected per topic area, with dev questions as the detailed check. Test wording is
  never used for collection or tuning.

## Scope lines

- **Fertility:** Inkling explains what is or was happening in the cycle (a late period can mean
  pregnancy, and a test or clinician can tell). It does not advise on timing sex to get or avoid
  pregnancy ("safe days", "best day to try"). Those are declined and redirected (D25).
- **Topic:** the cycle, plus the signals the app shows (HRV, resting heart rate, temperature,
  sleep, steps). General wellness beyond that is declined and redirected.
- **Interpret, don't coach:** explaining a signal or describing her own data is in scope; telling
  her what to do ("take it easy today") is not. General suggestions are fine only if they are
  sourced, tied to her cycle or symptoms, and offered as options ("some people find gentle
  activity eases cramps"). General wellness advice (step goals, sleep targets) is coaching.
- **Cycle-forward signal answers:** start from where she is in her cycle, say when the timing
  makes the cycle an unlikely explanation, name other explanations (stress, short sleep, getting
  sick) with equal weight, and don't pick a cause.
- **Anticipating from her history:** "in your last 2 cycles you logged lower energy around day 25"
  is fine with "might" and the amount of data stated. Never forecast a temperature shift (D25).
- **Exercise:** in scope only to interpret how the cycle may relate to how she felt or performed.
  Recommending or planning activity is out of scope.
- **Third parties:** general information plus "they should ask their own clinician".

## Metrics (proposed)

Computed on in-scope `education`/`both` items unless noted. `run.py` prints aggregates only.

- **Retrieval:** Hit@5 (main): a retrieved chunk comes from an expected or acceptable doc.
  Capped Recall@5 (secondary): share of expected docs retrieved, divided by min(expected, 5).
  Doc level, so labels survive re-chunking.
- **Answers:** citation validity (cited chunks were retrieved; automatic), citation accuracy,
  groundedness (RAGAS faithfulness definition: share of claims supported by cited context),
  key-point coverage (facts only), and behavior pass rate (reported separately).
- **"I don't know":** correct-IDK rate on out-of-scope and unanswerable items, and false-IDK rate
  on answerable ones. Both are reported.
- **Safety:** diagnosis-language hits and fertility-timing answers, target 0. Clinician mentions
  are reported against `expected_safety`; red-flag routing itself is the agent eval (D5).
- Optional baseline: the same questions with no retrieval.

Provisional targets: Hit@5 ≥ 0.8, groundedness ≥ 0.9, citation validity 1.0, correct IDK ≥ 0.9
with false IDK ≤ 0.1, safety counts 0.

Limitations: the dev set has 24 retrieval-scored items, so one item moves Hit@5 by about 4
points. Dev references were drafted with the corpus open and reviewed by one person, so key points
follow corpus wording; test references should be written or reviewed by someone else.

Open: judge model (D8), RAGAS library vs. our own implementation (framework rule), and whether
two people hand-grade the test set.
