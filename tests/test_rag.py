import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts import Evidence
from evals.rag.run import capped_recall, hit
from rag import corpus
from rag.corpus import (
    MAX_WORDS,
    Chunk,
    Skipped,
    chunk_text,
    extract,
    extract_blocks,
    fertility_flags,
    keep_sections,
    load_chunks,
    manifest,
    paper_text,
)
from rag.retriever import best_window, score_chunks, terms, to_evidence
from rag.stub import retrieve

QUESTIONS = Path(__file__).resolve().parents[1] / "evals" / "rag" / "questions"
FIELDS = {"id", "question", "context", "mode", "category", "in_scope", "group", "added"}
MODES = {"education", "summary", "both"}
CATEGORIES = {
    "cycle_basics",
    "symptoms",
    "late_irregular",
    "bleeding_red_flags",
    "birth_control",
    "pcos",
    "wearable",
    "clinician",
    "exercise",
    "weekly_review",
    "out_of_scope",
}


def load_questions(split: str) -> list[dict]:
    lines = (QUESTIONS / f"{split}.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_stub_matches_contract():
    results = retrieve("what is the luteal phase?")
    assert results and all(isinstance(e, Evidence) for e in results)


def make_chunk(i: int, text: str) -> Chunk:
    return Chunk(f"doc{i}", f"doc{i}#0", "NHS", "Title", "https://www.nhs.uk/x", text)


def test_extract_keeps_main_and_drops_page_furniture():
    html = """<html><head><title> Periods </title><style>.a{}</style></head><body>
    <svg><title>Logo</title></svg><nav>Menu</nav>
    <main><h1>Periods</h1><p>A cycle lasts<br>about 28 days.</p>
    <script>track()</script></main><footer>Cookies</footer></body></html>"""
    title, text = extract(html)
    assert title == "Periods"
    assert text.splitlines() == ["Periods", "A cycle lasts", "about 28 days."]


def test_chunks_respect_the_size_limit_and_keep_every_word():
    words = [f"w{i}" for i in range(500)]
    chunks = chunk_text("\n".join([" ".join(words[:50]), " ".join(words[50:])]))
    assert len(chunks) > 1
    assert all(len(c.split()) <= MAX_WORDS for c in chunks)
    assert set(" ".join(chunks).split()) == set(words)


def test_retrieval_ranks_the_matching_chunk_first():
    chunks = [
        make_chunk(0, "heavy periods can mean soaking a pad every hour"),
        make_chunk(1, "the pill is a birth control method"),
    ]
    assert score_chunks("how heavy is too heavy for periods", chunks)[0][1].doc_id == "doc0"


def test_retrieval_returns_nothing_without_a_match():
    assert score_chunks("best pizza nearby", [make_chunk(0, "heavy periods")]) == []


def test_evidence_matches_contract_with_verbatim_snippet():
    chunk = make_chunk(0, "heavy periods can mean soaking a pad every hour")
    evidence = to_evidence(chunk, "heavy", datetime(2026, 11, 1, tzinfo=UTC))
    assert isinstance(evidence, Evidence)
    assert evidence.snippet in chunk.text


def test_extract_recovers_from_unclosed_tags_in_skipped_regions():
    html = "<nav><ul><li>Home<li>About<source></ul></nav><main><p>Care advice.</p></main>"
    assert extract(html)[1] == "Care advice."


def test_extract_keeps_callouts_inside_main_and_drops_reference_lists():
    html = """<header>Site</header><main><aside><p>Call a doctor.</p></aside><p>Body.</p>
    <h2>Sources</h2><p>Smith 2020.</p></main>"""
    assert extract(html)[1].splitlines() == ["Call a doctor.", "Body."]


def test_snippet_shows_the_matching_passage():
    text = " ".join(["filler"] * 150 + ["soaking", "a", "pad"])
    assert "soaking" in best_window(text, {"soaking"})


def test_terms_fold_plurals_and_expand_abbreviations():
    assert terms("side effects of bc") == ["side", "effect", "birth", "control"]


def test_only_manifest_documents_are_indexed(tmp_path):
    doc_id = manifest()[0]["doc_id"]
    for name in (doc_id, "not-on-the-whitelist"):
        doc = {"doc_id": name, "source_org": "X", "title": "T", "url": "u", "text": "words"}
        (tmp_path / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")
    assert {c.doc_id for c in load_chunks(tmp_path)} == {doc_id}


def test_fertility_timing_chunks_are_flagged():
    assert fertility_flags([make_chunk(0, "Track your fertile days here")]) == ["doc0#0"]


def test_question_schema():
    for q in load_questions("dev") + load_questions("test"):
        assert set(q) == FIELDS, q["id"]
        assert q["question"].strip() and q["mode"] in MODES and q["category"] in CATEGORIES
        assert isinstance(q["in_scope"], bool)


def test_split_has_no_leaks():
    dev, test = load_questions("dev"), load_questions("test")
    ids = Counter(q["id"] for q in dev + test)
    assert all(n == 1 for n in ids.values()), "duplicate id"
    dev_groups = {q["group"] for q in dev} - {None}
    test_groups = {q["group"] for q in test} - {None}
    assert not dev_groups & test_groups, "a near-twin group spans dev and test"


def test_every_category_on_both_sides():
    dev, test = load_questions("dev"), load_questions("test")
    assert {q["category"] for q in dev} == {q["category"] for q in test} == CATEGORIES


MANIFEST = Path(__file__).resolve().parents[1] / "rag" / "manifest.csv"
REFERENCES = QUESTIONS.parent / "references" / "dev.jsonl"
REF_FIELDS = {
    "id",
    "expected_doc_ids",
    "acceptable_doc_ids",
    "key_points",
    "behaviors",
    "expected_safety",
    "idk_expected",
    "notes",
}


def test_dev_references_match_questions_and_manifest():
    refs = [json.loads(line) for line in REFERENCES.read_text().splitlines() if line.strip()]
    doc_ids = {r["doc_id"] for r in csv.DictReader(MANIFEST.open())}
    assert sorted(r["id"] for r in refs) == sorted(q["id"] for q in load_questions("dev"))
    for r in refs:
        assert set(r) == REF_FIELDS, r["id"]
        assert r["expected_safety"] in {"none", "caution", "red_flag"}, r["id"]
        assert isinstance(r["idk_expected"], bool), r["id"]
        expected, acceptable = set(r["expected_doc_ids"]), set(r["acceptable_doc_ids"])
        assert expected | acceptable <= doc_ids, r["id"]
        assert not expected & acceptable, f"{r['id']}: a doc is both expected and acceptable"
        points = r["key_points"] + r["behaviors"]
        assert points and all(p.strip() for p in points), r["id"]


def test_manifest_is_valid():
    rows = list(csv.DictReader(MANIFEST.open()))
    assert rows and len({r["doc_id"] for r in rows}) == len(rows), "duplicate doc_id"
    for r in rows:
        assert r["url"].startswith("https://"), r["doc_id"]
        assert r["doc_type"] in {"page", "research", "device_docs"}, r["doc_id"]
        assert r["license"] in {"public domain", "CC BY", "CC BY-NC", "CC BY 4.0"}, r["doc_id"]
        if r["doc_type"] == "research":
            assert r["population"].strip(), f"{r['doc_id']}: say who was studied"


PAPER_XML = b"""<article><front><article-meta>
<title-group><article-title>HRV across the cycle</article-title></title-group>
<permissions><license><ali:license_ref xmlns:ali="http://www.niso.org/schemas/ali/1.0/">
https://creativecommons.org/licenses/LICENSE/4.0/</ali:license_ref></license></permissions>
<abstract><p>HRV falls late in the cycle.</p></abstract></article-meta></front>
<body><sec><title>Introduction</title><p>Background.</p></sec>
<sec><title>Methods</title><p>We recruited 40 people.</p></sec>
<sec><title>Results</title><p>HRV was lower.</p>
<sec><title>Subgroups</title><p>Same.</p></sec></sec>
</body><back><ref-list><ref>Smith 2020.</ref></ref-list></back></article>"""


def test_paper_text_keeps_findings_and_drops_methods_and_references():
    title, license_name, text = paper_text(PAPER_XML.replace(b"LICENSE", b"by"))
    assert (title, license_name) == ("HRV across the cycle", "CC BY")
    assert text.splitlines() == [
        "Abstract",
        "HRV falls late in the cycle.",
        "Introduction",
        "Background.",
        "Results",
        "HRV was lower.",
        "Subgroups",
        "Same.",
    ]


def test_paper_without_an_open_license_is_skipped():
    with pytest.raises(Skipped):
        paper_text(PAPER_XML.replace(b"LICENSE", b"by-nc-nd"))


def test_device_docs_keep_only_listed_sections():
    html = """<main><h1>Vitals</h1><p>Intro.</p><h2>Temperature</h2><p>Skin temp is relative.</p>
    <h3>REST representation example</h3><p>{json}</p><h2>Blood glucose</h2><p>mg/dL</p></main>"""
    _, blocks = extract_blocks(html)
    assert keep_sections(blocks, {"Temperature"}).splitlines() == [
        "Temperature",
        "Skin temp is relative.",
    ]


def test_research_rows_are_fetched_from_europe_pmc(monkeypatch):
    requested = []

    class Response:
        content = PAPER_XML.replace(b"LICENSE", b"by-nc")

    monkeypatch.setattr(corpus, "_get", lambda url, robots: requested.append(url) or Response())
    row = {
        "doc_id": "pmid-1",
        "doc_type": "research",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/",
    }
    title, text = corpus.fetch_text(row, {})
    assert requested == [corpus.EUROPE_PMC.format(pmcid="PMC123")]
    assert "HRV was lower." in text and "We recruited" not in text


def test_hit_counts_acceptable_docs_and_recall_counts_only_expected():
    retrieved = ["a", "a", "x", "y", "z"]
    assert hit(retrieved, {"b"}, {"x"}) == 1
    assert hit(retrieved, {"b"}, set()) == 0
    assert capped_recall(retrieved, {"a", "b"}) == 0.5
    assert capped_recall(retrieved, {"a", "b", "c", "d", "e", "f", "g"}) == 1 / 5
