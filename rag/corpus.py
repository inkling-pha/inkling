"""Trusted corpus: fetch the documents in manifest.csv, extract their text, split it into chunks.

Run from the repo root: python -m rag.corpus
Fetched text goes to data/raw/corpus/ (gitignored). Only documents in the manifest are indexed
(D26), and links found on pages are never followed.

Pages are HTML. Papers come from Europe PMC's full-text API (its robots.txt allows it; NCBI's
E-utilities and PMC article pages don't). Device docs keep only the sections listed below.
"""

import csv
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("manifest.csv")
CORPUS_DIR = REPO_ROOT / "data" / "raw" / "corpus"

# Name the project and link it, as polite crawlers do. CDC rejects the bare name with a 403.
USER_AGENT = "InklingCourseProject/0.1 (+https://github.com/gracey0630/inkling)"
REQUEST_DELAY_S = 2
MIN_WORDS = 50

# Page furniture outside <main>. Inside <main>, header and aside can hold headings and care advice.
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "form"}
SKIP_OUTSIDE_MAIN = SKIP_TAGS | {"header", "footer", "aside"}
REFERENCE_HEADINGS = {"sources", "references", "citations"}
FERTILITY_TIMING = re.compile(
    r"fertile (days|window)|safe days|ovulation calculator|best (day|time) to (try|conceive)", re.I
)
BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "br", "div", "section"}
MAX_WORDS = 180
OVERLAP_WORDS = 30
HEADING_TAGS = {"h1", "h2", "h3", "h4"}

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
# Licenses that let us store the text (D26). CC BY-NC-ND and closed papers are skipped.
OPEN_LICENSES = {"by": "CC BY", "by-nc": "CC BY-NC", "zero": "CC0"}
SKIP_PAPER_SECTIONS = re.compile(
    r"method|material|statistic|funding|acknowledg|conflict|competing|contribution|"
    r"availability|supplementa|ethic",
    re.I,
)
# Device docs explain how the watch measures a signal (sources.md): keep only these sections.
DEVICE_DOC_SECTIONS = {
    "google-health-api-vitals": {"Heart rate and heart health", "Temperature"},
    "google-health-api-sleep": {
        "Sleep sessions and short awakenings",
        "Sleep efficiency and latency metrics",
        "Sleep efficiency score",
        "Sleep onset latency",
        "Daily sleep temperature derivations",
        "Respiratory rate",
        "Heart rate variability (HRV)",
        "Holistic view of sleep health and recovery",
    },
    "google-health-api-skin-temperature": {
        "Sensor hardware architectures",
        "Internal device temperature",
        "Ambient Compensated Skin Temperature",
        "Interpreting temperature values and deltas",
        "Working with deltas",
        "Daily Sleep Temperature Derivations",
    },
}
# Passages cut out before chunking, as (first words, last words), both verbatim and inclusive.
# Why each one is cut is in the manifest notes (fertility review D25, outdated or off-topic text).
EXCLUDE: dict[str, list[tuple[str, str]]] = {
    "cdc-spr-intrauterine-contraception": [
        ("If the day of ovulation can be estimated", "not occur >5 days after ovulation."),
        ("Switching from a Cu-IUD:", "to address the potential for residual sperm."),
    ],
    "cdc-spr-combined-hormonal-contraceptives": [
        (
            "Switching from an intrauterine device (IUD):",
            "CHCs may be started no sooner than 5 days after use of UPA. If it has been >5 days"
            " since menstrual bleeding started, the patient needs to abstain from sexual"
            " intercourse or use barrier methods (e.g., condoms) for the next 7 days.",
        ),
    ],
    "cdc-spr-progestin-only-pills": [
        (
            "Switching from an intrauterine device (IUD):",
            "All POPs may be started no sooner than 5 days after use of UPA. The patient should"
            " also follow the back-up contraception recommendations for either norethindrone or"
            " norgestrel POPs or for DRSP POPs.",
        ),
    ],
    "cdc-spr-implants": [
        (
            "Switching from an IUD:",
            "(with the exception of UPA) at the time of IUD removal. If it has been >5 days since"
            " menstrual bleeding started, the patient needs to abstain from sexual intercourse or"
            " use barrier methods (e.g., condoms) for the next 7 days.",
        ),
    ],
    "fda-birth-control": [
        (
            "A medical software application (app) that can be used as a method of contraception",
            "hormonal treatments that prevent ovulation (release of egg).",
        ),
    ],
    "nichd-contraception-types": [
        ("A sterilization implant is a nonsurgical", "show that the tubes are fully blocked."),
    ],
    "nichd-menstruation-and-menstrual-problems": [
        ("A woman can tell when she has begun ovulating", "may be a signal of ovulation."),
    ],
    "owh-polycystic-ovary-syndrome": [
        ("You can also use our Ovulation Calculator", "you are most likely to be fertile."),
    ],
    "pmid-40909206": [
        (
            "The monitoring of fertile windows",
            "has been reported using the Oura ring more recently118.",
        ),
    ],
    "pmid-32442161": [
        (
            "For more than 30 years, the notion",
            "the fertile window extends before and after ovulation [1].",
        ),
        ("Comparatively, calendar-based apps", "the menstrual records of the past 6 cycles [6]."),
        ("An app estimating ovulation", "may be limited in its effectiveness."),
    ],
    "pmid-39008822": [
        (
            "Exercise interventions directed for weight loss",
            "which may influence energy intake.12,13",
        ),
        ("; however, variable and best detected using", "predict the onset of ovulation"),
    ],
}


class Skipped(Exception):
    """A document we deliberately don't store; the message says why."""


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: str
    source_org: str
    title: str
    url: str
    text: str


class _Text(HTMLParser):
    """Collect visible text as blocks, keeping only <main> when the page has one."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.all_blocks: list[tuple[int, str]] = []  # (heading level or 0, text)
        self.main_blocks: list[tuple[int, str]] = []
        self._buf: list[str] = []
        self._level = 0
        self._skip_tag = ""
        self._skip_depth = 0
        self._main = 0
        self._in_title = False

    def _flush(self):
        text = " ".join("".join(self._buf).split())
        self._buf = []
        if text:
            self.all_blocks.append((self._level, text))
            if self._main:
                self.main_blocks.append((self._level, text))

    def handle_starttag(self, tag, attrs):
        if self._skip_tag:
            self._skip_depth += tag == self._skip_tag
        elif tag == "br":
            self._flush()
        elif tag in SKIP_OUTSIDE_MAIN and (tag in SKIP_TAGS or not self._main):
            self._skip_tag, self._skip_depth = tag, 1
        elif tag == "title":
            self._in_title = True
        elif tag == "main":
            self._flush()
            self._main += 1
        elif tag in BLOCK_TAGS:
            self._flush()
            if tag in HEADING_TAGS:
                self._level = int(tag[1])

    def handle_endtag(self, tag):
        if self._skip_tag:
            self._skip_depth -= tag == self._skip_tag
            if not self._skip_depth:
                self._skip_tag = ""
        elif tag == "title":
            self._in_title = False
        elif tag == "main":
            self._flush()
            self._main = max(0, self._main - 1)
        elif tag in BLOCK_TAGS:
            self._flush()
            if tag in HEADING_TAGS:
                self._level = 0

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_tag:
            self._buf.append(data)


def extract_blocks(html: str) -> tuple[str, list[tuple[int, str]]]:
    """Return (title, blocks), each block a (heading level or 0, text) pair."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    parser._flush()
    blocks = parser.main_blocks or parser.all_blocks
    for i, (_, block) in enumerate(blocks):
        if block.lower().rstrip(":") in REFERENCE_HEADINGS:
            blocks = blocks[:i]
            break
    return " ".join(parser.title.split()), blocks


def extract(html: str) -> tuple[str, str]:
    """Return (title, text) with one block per line."""
    title, blocks = extract_blocks(html)
    return title, "\n".join(text for _, text in blocks)


def keep_sections(blocks: list[tuple[int, str]], headings: set[str]) -> str:
    """Text under the listed h2-h4 headings only; any other heading ends a kept section."""
    kept, keeping = [], False
    for level, text in blocks:
        if level >= 2:
            keeping = text in headings
        if keeping:
            kept.append(text)
    return "\n".join(kept)


def _text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def paper_text(xml: bytes) -> tuple[str, str, str]:
    """Return (title, license, text) from Europe PMC JATS XML. Raises Skipped if not open."""
    root = ET.fromstring(xml)
    found = re.search(rb"creativecommons\.org/(?:licenses|publicdomain)/([a-z-]+)", xml)
    code = found.group(1).decode() if found else "none"
    license_name = OPEN_LICENSES.get(code)
    if not license_name:
        raise Skipped(f"license not open enough to store: {code}")
    title_el = root.find(".//article-meta//article-title")
    blocks = ["Abstract"] + [_text(p) for p in root.findall(".//article-meta/abstract//p")]

    def add_section(sec: ET.Element):
        title = sec.find("title")
        if title is not None and SKIP_PAPER_SECTIONS.search(_text(title)):
            return
        if title is not None:
            blocks.append(_text(title))
        blocks.extend(_text(p) for p in sec.findall("p"))
        for child in sec.findall("sec"):
            add_section(child)

    for sec in root.findall("./body/sec"):
        add_section(sec)
    text = "\n".join(b for b in blocks if b)
    return (_text(title_el) if title_el is not None else ""), license_name, text


def chunk_text(text: str) -> list[str]:
    """Group blocks into chunks of up to MAX_WORDS, overlapping when a chunk is cut."""
    chunks: list[str] = []
    words: list[str] = []
    for block in text.splitlines():
        block_words = block.split()
        if words and len(words) + len(block_words) > MAX_WORDS:
            chunks.append(" ".join(words))
            words = words[-OVERLAP_WORDS:]
        words += block_words
        while len(words) > MAX_WORDS:
            chunks.append(" ".join(words[:MAX_WORDS]))
            words = words[MAX_WORDS - OVERLAP_WORDS :]
    if words:
        chunks.append(" ".join(words))
    return chunks


def manifest(path: Path = MANIFEST) -> list[dict]:
    """The manifest's documents."""
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def robots_allow(url: str, cache: dict[str, RobotFileParser]) -> bool:
    """Unreadable robots.txt counts as not allowed, so we only fetch what we confirmed."""
    parts = urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    if host not in cache:
        rules = RobotFileParser()
        response = requests.get(
            f"{host}/robots.txt", timeout=30, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
        rules.parse(response.text.splitlines())
        cache[host] = rules
    return cache[host].can_fetch(USER_AGENT, url)


def _get(url: str, robots: dict[str, RobotFileParser]) -> requests.Response:
    if not robots_allow(url, robots):
        raise Skipped("blocked by robots.txt")
    time.sleep(REQUEST_DELAY_S)
    response = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    if "charset" not in response.headers.get("content-type", "").lower():
        response.encoding = "utf-8"  # requests would guess Latin-1 and garble the text
    return response


def fetch_text(row: dict, robots: dict[str, RobotFileParser]) -> tuple[str, str]:
    """Return (title, text) for one manifest row, by document type."""
    if row["doc_type"] == "research":
        pmcid = re.search(r"PMC\d+", row["url"])
        if not pmcid:
            raise Skipped("research url has no PMC id")
        response = _get(EUROPE_PMC.format(pmcid=pmcid.group(0)), robots)
        title, _, text = paper_text(response.content)
        return title, text
    title, blocks = extract_blocks(_get(row["url"], robots).text)
    if row["doc_type"] == "device_docs":
        if row["doc_id"] not in DEVICE_DOC_SECTIONS:
            raise Skipped("no sections listed in DEVICE_DOC_SECTIONS")
        return title, keep_sections(blocks, DEVICE_DOC_SECTIONS[row["doc_id"]])
    return title, "\n".join(text for _, text in blocks)


def fetch_all(corpus_dir: Path = CORPUS_DIR) -> dict[str, str]:
    """Fetch the documents and return {doc_id: "ok" or why not}. A failure keeps the old copy."""
    corpus_dir.mkdir(parents=True, exist_ok=True)
    status = {}
    robots: dict[str, RobotFileParser] = {}
    for row in manifest():
        doc_id = row["doc_id"]
        try:
            title, text = fetch_text(row, robots)
        except Skipped as reason:
            status[doc_id] = f"skipped: {reason}"
            continue
        except (requests.RequestException, ET.ParseError) as err:
            status[doc_id] = type(err).__name__
            print(f"FAILED {doc_id}: {err}", file=sys.stderr)
            continue
        if len(text.split()) < MIN_WORDS:
            status[doc_id] = "too little text extracted"
            continue
        doc = {
            "doc_id": doc_id,
            "source_org": row["org"],
            "url": row["url"],
            "title": row["title"] or title,
            "text": text,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        path = corpus_dir / f"{doc_id}.json"
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        status[doc_id] = "ok"
    return status


def cut_passages(text: str, spans: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """Remove each (first words, last words) span. Returns the text and spans not found."""
    missing = []
    for first, last in spans:
        start = text.find(first)
        end = text.find(last, start) if start >= 0 else -1
        if end < 0:
            missing.append(first)
            continue
        text = text[:start] + text[end + len(last) :]
    return text, missing


def load_chunks(corpus_dir: Path = CORPUS_DIR) -> list[Chunk]:
    chunks = []
    for row in manifest():
        path = corpus_dir / f"{row['doc_id']}.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        text, missing = cut_passages(doc["text"], EXCLUDE.get(row["doc_id"], []))
        for first in missing:
            # The page changed since review: the passage may now be indexed. Re-review it.
            print(f"EXCLUDE not found in {row['doc_id']}: {first!r}", file=sys.stderr)
        for i, chunk in enumerate(chunk_text(text)):
            chunks.append(
                Chunk(
                    doc_id=doc["doc_id"],
                    chunk_id=f"{doc['doc_id']}#{i}",
                    source_org=doc["source_org"],
                    title=doc["title"],
                    url=doc["url"],
                    text=chunk,
                )
            )
    return chunks


def fertility_flags(chunks: list[Chunk]) -> list[str]:
    """Chunk ids for a person to review before indexing (sources.md)."""
    return [c.chunk_id for c in chunks if FERTILITY_TIMING.search(c.text)]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


if __name__ == "__main__":
    results = fetch_all()
    flagged = fertility_flags(load_chunks())
    print(json.dumps({"status": results, "review_fertility_timing": flagged}, indent=2))
