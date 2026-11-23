# Trusted sources

The RAG corpus whitelist (D26). Education answers cite only these; if nothing relevant is
retrieved, the answer is "I don't know". The per-document list lives in `rag/manifest.csv`.

## What we store

We store text only if we're allowed to: US government work (public domain) or an open license.

| Source | Why trusted | License | Covers |
|---|---|---|---|
| **Office on Women's Health** (HHS) | Federal women's-health office, written for a lay audience | Public domain | Cycle, PMS, period problems, PCOS, birth control methods, yeast infections |
| **NICHD** (NIH) | Federal research institute for reproductive health | Public domain | Irregular periods, amenorrhea, PCOS, vaginitis, contraception FAQs |
| **MedlinePlus** (NLM), health-topic pages only | NIH's consumer health site, no ads | Public domain | Menstruation, PMS, period pain, vaginitis |
| **CDC** | Federal public-health agency; sets US contraception guidance (US SPR) | Public domain | Birth control methods, missed pills, heavy bleeding, BV, condoms |
| **FDA** | Federal regulator of menstrual products | Public domain | Tampon safety and toxic shock syndrome |
| **Peer-reviewed papers** (PubMed Central) | Peer-reviewed; meta-analyses and large cohorts preferred | CC BY or CC BY-NC | How wearable signals change across the cycle and with birth control; sleep, mood, stress; exercise; cycle length |
| **Google Health API docs** | Defines how the Fitbit metrics are computed | CC BY 4.0 | What each signal measures (skin temperature, HRV, resting heart rate, sleep) |

Papers must be about the cycle or a signal the app shows. Developer docs explain measurement only,
never health claims.

## What we don't store

- **Fertility-timing content** (D25): OWH's ovulation calculator, fertility pages, and papers built
  to predict ovulation or the fertile window.
- **Copyrighted text:** MedlinePlus Medical Encyclopedia and drug pages, AHA, Mayo Clinic,
  Cleveland Clinic, ACOG, and Google's help center. These may come back later as link-only
  "read more" sources (see the timeline).
- **OpenStax textbooks:** CC BY-NC-SA, and the pages forbid ingestion into LLMs or generative AI.
- **NHS:** openly licensed, but UK guidance. Replaced with US equivalents.
- **Forums, marketing pages, low-quality journals.**

## Rules

- Each document has a `doc_type`: `page`, `research` or `device_docs`.
- Research is phrased as "studies found, on average", never applied to one person as a diagnosis.
- Each paper's manifest row says who was studied (`population`). Answers that cite a paper say so
  and note when it may not fit the user (e.g. a study of medical students only).
- Fertility-review decisions are recorded in the manifest `notes`. Passages to exclude are listed in
  `rag/corpus.py` (`EXCLUDE`, verbatim first and last words) and cut out before chunking. If a
  re-fetched page no longer has a listed passage, indexing prints a warning: review it again.
- At indexing time, chunks mainly about fertility timing are flagged for review by a person.
- Known limitation: the runtime guard (`agent/fertility_guard.py`) drops any retrieved snippet the
  `FERTILITY_TIMING` regex matches, including passages a person reviewed and kept (e.g. the
  fertility-awareness descriptions). Safe direction, but it can turn those answers into "I don't
  know". Narrowing the regex is proposed for the team.
- Only documents in the manifest are indexed; links found on pages are never followed.

## Access notes

- Check each site's robots.txt before fetching, and wait between requests. Identify the fetcher
  with a project name and link: CDC returns 403 to a bare name.
- Papers: fetch full text from Europe PMC's REST API (`/europepmc/webservices/rest/<PMCID>/fullTextXML`);
  the license is in the XML. NCBI's E-utilities are disallowed by robots.txt, and PMC article pages
  return 403 to scripts. Citations still link to the PMC article page.
- CDC Stacks (`stacks.cdc.gov/view/...`) pages are catalog records, not the document text.
- MedlinePlus: only health-topic pages (`medlineplus.gov/<topic>.html`) are public domain.
  `/ency/` and `/druginfo/` pages are copyrighted.
- CDC's US SPR pages are written for clinicians, so answers need to rephrase them plainly.
- Google Health API docs: store only the sections listed in `rag/corpus.py` (`DEVICE_DOC_SECTIONS`).
