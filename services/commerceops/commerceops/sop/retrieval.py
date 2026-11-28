"""BM25 citation search over the packaged SOP markdown.

Ranking uses latin words and CJK bigrams. The quote is an exact slice of the
source file. This is not a vector index and it does not call an embedding API.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import math
from pathlib import Path
import re

FORMULA_VERSION = "sop.bm25.v1"
K1 = 1.5
B = 0.75

_DOCS_DIR = Path(__file__).resolve().parent / "docs"
_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CJK = re.compile(r"[\u4e00-\u9fff]+")
_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)
# A dot between digits is a decimal, not a sentence boundary.
_SENTENCE = re.compile(r"[^.。\n]+(?:\.\d+[^.。\n]*)*[.。]?")

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "for",
        "in",
        "on",
        "with",
        "by",
        "is",
        "are",
        "be",
        "this",
        "that",
        "as",
        "at",
        "from",
        "into",
        "it",
        "we",
        "our",
        "you",
        "your",
        "when",
        "than",
        "then",
        "not",
        "do",
        "does",
        "if",
        "its",
        "their",
        "they",
        "them",
        "but",
        "so",
        "such",
        "can",
        "may",
        "must",
    }
)


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    title: str
    section: str
    text: str
    source_text: str
    source_sha256: str


@dataclass(frozen=True)
class SopSource:
    doc_id: str
    title: str
    version: str
    body: str
    sha256: str
    path: str


@dataclass(frozen=True)
class Citation:
    doc_id: str
    title: str
    section: str
    quote: str
    score: str
    source_sha256: str
    formula_version: str = FORMULA_VERSION


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN.finditer(text.lower()):
        token = match.group(0)
        if len(token) < 2 or token in STOPWORDS:
            continue
        tokens.append(token)
    for run in _CJK.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError("SOP is missing frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SOP frontmatter is not closed")
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"')
    return meta, text[end + 5 :]


def load_package_documents() -> list[SopSource]:
    documents: list[SopSource] = []
    for path in sorted(_DOCS_DIR.glob("*.md")):
        raw = path.read_bytes()
        text = raw.decode("utf-8").replace("\r\n", "\n")
        meta, body = _parse_frontmatter(text)
        documents.append(
            SopSource(
                doc_id=meta["doc_id"],
                title=meta["title"],
                version=meta.get("version", ""),
                body=body,
                sha256=sha256(raw).hexdigest(),
                path=str(path),
            )
        )
    if len(documents) < 4:
        raise RuntimeError("expected the four packaged SOP documents")
    return documents


def chunks_for(document: SopSource, source_text: str | None = None) -> list[Chunk]:
    text = source_text if source_text is not None else Path(document.path).read_text(encoding="utf-8")
    matches = list(_HEADING.finditer(document.body))
    if not matches:
        raise ValueError(f"{document.doc_id} has no sections")
    chunks: list[Chunk] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document.body)
        chunks.append(
            Chunk(
                doc_id=document.doc_id,
                title=document.title,
                section=match.group(1).strip(),
                text=document.body[match.start() : end].strip(),
                source_text=text,
                source_sha256=document.sha256,
            )
        )
    return chunks


class BM25Index:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.term_freqs: list[Counter[str]] = []
        self.doc_freq: Counter[str] = Counter()
        self.lengths: list[int] = []
        for chunk in chunks:
            counts = Counter(tokenize(chunk.text))
            self.term_freqs.append(counts)
            self.lengths.append(sum(counts.values()) or 1)
            for term in counts:
                self.doc_freq[term] += 1
        self.average_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        self.size = len(chunks)

    def search(self, query: str, limit: int) -> list[Citation]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []
        scored: list[tuple[float, int]] = []
        for index, freqs in enumerate(self.term_freqs):
            score = 0.0
            length = self.lengths[index]
            for term in set(terms):
                frequency = freqs.get(term)
                if not frequency:
                    continue
                doc_freq = self.doc_freq[term]
                idf = math.log(1 + (self.size - doc_freq + 0.5) / (doc_freq + 0.5))
                denominator = frequency + K1 * (1 - B + B * length / self.average_length)
                score += idf * (frequency * (K1 + 1)) / denominator
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], self.chunks[item[1]].doc_id, self.chunks[item[1]].section))
        hits: list[Citation] = []
        for score, index in scored[:limit]:
            chunk = self.chunks[index]
            hits.append(
                Citation(
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    section=chunk.section,
                    quote=_select_quote(chunk, terms),
                    score=format(score, ".6f"),
                    source_sha256=chunk.source_sha256,
                )
            )
        return hits


def _select_quote(chunk: Chunk, terms: list[str]) -> str:
    sentences = [match.group(0).strip() for match in _SENTENCE.finditer(chunk.text) if match.group(0).strip()]
    if not sentences:
        quote = chunk.text.strip()
    else:
        wanted = set(terms)
        best = sentences[0]
        best_overlap = -1
        for sentence in sentences:
            overlap = len(wanted & set(tokenize(sentence)))
            if overlap > best_overlap:
                best = sentence
                best_overlap = overlap
        quote = best
    if quote not in chunk.source_text:
        raise RuntimeError(f"citation quote is not an exact slice of {chunk.doc_id}")
    return quote


def build_index(documents: list[SopSource] | None = None) -> BM25Index:
    docs = documents if documents is not None else load_package_documents()
    chunks: list[Chunk] = []
    for document in docs:
        source_text = Path(document.path).read_text(encoding="utf-8") if document.path else document.body
        chunks.extend(chunks_for(document, source_text))
    return BM25Index(chunks)


_INDEX: BM25Index | None = None


def get_index() -> BM25Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = build_index()
    return _INDEX


def search_sops(query: str, limit: int = 5) -> dict:
    if limit < 1 or limit > 20:
        raise ValueError("limit must be between 1 and 20")
    hits = get_index().search(query, limit) if query.strip() else []
    return {
        "formula_version": FORMULA_VERSION,
        "tokenizer": "latin_words_and_cjk_bigrams",
        "k1": str(K1),
        "b": str(B),
        "query": query,
        "hits": hits,
    }
