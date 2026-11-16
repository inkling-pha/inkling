"""Retrieval metrics on the dev questions: python -m evals.rag.run

Dev only: test.jsonl is held out. Scores in-scope education/both questions against
references/dev.jsonl (see the README): Hit@5 is the headline, capped Recall@5 a diagnostic.
Prints aggregates and question ids only, never document text.
"""

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from rag.corpus import load_chunks
from rag.retriever import retrieve, score_chunks

HERE = Path(__file__).parent
DEV = HERE / "questions" / "dev.jsonl"
REFERENCES = HERE / "references" / "dev.jsonl"
K = 5


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def query_for(question: dict) -> str:
    return " ".join(filter(None, [question["question"], question["context"]]))


def hit(retrieved: list[str], expected: set[str], acceptable: set[str]) -> int:
    return int(bool(set(retrieved) & (expected | acceptable)))


def capped_recall(retrieved: list[str], expected: set[str], k: int = K) -> float:
    return len(set(retrieved) & expected) / min(len(expected), k)


def scored_questions(questions: list[dict], references: dict[str, dict]) -> list[dict]:
    """In-scope education/both questions that have expected docs."""
    return [
        q
        for q in questions
        if q["in_scope"] and q["mode"] != "summary" and references[q["id"]]["expected_doc_ids"]
    ]


def main() -> dict:
    chunks = load_chunks()
    questions = read_jsonl(DEV)
    references = {r["id"]: r for r in read_jsonl(REFERENCES)}

    hits, recalls, distinct, misses = [], [], [], []
    by_category = defaultdict(list)
    for q in scored_questions(questions, references):
        ref = references[q["id"]]
        expected, acceptable = set(ref["expected_doc_ids"]), set(ref["acceptable_doc_ids"])
        retrieved = [e.doc_id for e in retrieve(query_for(q), k=K)]
        h = hit(retrieved, expected, acceptable)
        hits.append(h)
        recalls.append(capped_recall(retrieved, expected))
        distinct.append(len(set(retrieved)))
        by_category[q["category"]].append(h)
        if not h:
            misses.append(q["id"])

    top_scores = defaultdict(list)
    for q in questions:
        if q["mode"] != "summary":
            scored = score_chunks(query_for(q), chunks)
            top_scores[q["category"]].append(scored[0][0] if scored else 0.0)

    return {
        "docs": len({c.doc_id for c in chunks}),
        "chunks": len(chunks),
        "questions_scored": len(hits),
        f"hit@{K}": round(mean(hits), 2),
        f"capped_recall@{K}": round(mean(recalls), 2),
        f"distinct_docs_in_top{K}": round(mean(distinct), 1),
        f"hit@{K}_by_category": {c: round(mean(v), 2) for c, v in sorted(by_category.items())},
        "misses": misses,
        "median_top_score_by_category": {
            c: round(median(v), 2) for c, v in sorted(top_scores.items())
        },
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
