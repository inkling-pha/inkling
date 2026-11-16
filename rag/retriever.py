"""BM25 keyword retrieval over the trusted corpus.

A dependency-free baseline, not the answer to D12: it runs the pipeline and gives embeddings
something to beat. It keeps the stub's retrieve() signature so it can replace it.

A positive score only means a shared word, not relevance. Scope decisions (D27) can't rest on it.
"""

import math
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache

from contracts import Evidence
from rag.corpus import Chunk, load_chunks, tokenize

K1 = 1.5
B = 0.75
SNIPPET_WORDS = 60
STOPWORDS = frozenset(
    "a about am an and are as at be been but by can could do does for from had has have how i if "
    "in is it its me my of on or so that the their them they this to was what when where which "
    "who why will with would you your".split()
)


ABBREVIATIONS = {"bc": ["birth", "control"]}


def normalize(token: str) -> str:
    """Fold plurals so "effect" matches "effects"."""
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def terms(text: str) -> list[str]:
    expanded = [t for token in tokenize(text) for t in ABBREVIATIONS.get(token, [token])]
    return [normalize(t) for t in expanded if t not in STOPWORDS]


def score_chunks(query: str, chunks: list[Chunk]) -> list[tuple[float, Chunk]]:
    """Chunks with at least one query term, best first."""
    docs = [Counter(terms(c.text)) for c in chunks]
    if not docs:
        return []
    lengths = [sum(d.values()) for d in docs]
    avg_length = sum(lengths) / len(docs)
    query_terms = set(terms(query))
    idf = {}
    for term in query_terms:
        df = sum(term in d for d in docs)
        idf[term] = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
    scored = []
    for doc, length, chunk in zip(docs, lengths, chunks, strict=True):
        score = 0.0
        for term in query_terms:
            tf = doc[term]
            score += idf[term] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / avg_length))
        if score > 0:
            scored.append((score, chunk))
    return sorted(scored, key=lambda pair: pair[0], reverse=True)


def best_window(text: str, query_terms: set[str]) -> str:
    """The SNIPPET_WORDS-long stretch of the chunk with the most query terms."""
    words = text.split()
    hits = [any(t in query_terms for t in terms(word)) for word in words]
    starts = range(max(1, len(words) - SNIPPET_WORDS + 1))
    best = max(starts, key=lambda i: sum(hits[i : i + SNIPPET_WORDS]))
    return " ".join(words[best : best + SNIPPET_WORDS])


def to_evidence(chunk: Chunk, query: str, retrieved_at: datetime) -> Evidence:
    return Evidence(
        doc_id=chunk.doc_id,
        chunk_id=chunk.chunk_id,
        source_org=chunk.source_org,
        title=chunk.title,
        url=chunk.url,
        snippet=best_window(chunk.text, set(terms(query))),
        retrieved_at=retrieved_at,
    )


@lru_cache(maxsize=1)
def _corpus() -> tuple[Chunk, ...]:
    chunks = tuple(load_chunks())
    if not chunks:
        raise RuntimeError("Corpus is empty. Run: python -m rag.corpus")
    return chunks


def retrieve(query: str, user_context: dict | None = None, k: int = 5) -> list[Evidence]:
    """Top-k chunks sharing a word with the query, as Evidence. Empty means no word matched."""
    now = datetime.now(UTC)
    scored = score_chunks(query, list(_corpus()))[:k]
    return [to_evidence(chunk, query, now) for _, chunk in scored]
