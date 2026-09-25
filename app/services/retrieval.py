from __future__ import annotations

import re
import json
from collections import defaultdict
from datetime import date

from app.database import Database
from app.config import settings
from app.schemas import RetrievedChunk

STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "by", "does", "for", "from", "how", "in",
    "is", "it", "of", "on", "or", "say", "the", "to", "was", "what", "when", "where", "which", "who",
    "why", "will", "with",
    "according", "describe", "describes", "suggest", "suggests", "recommend", "recommends",
    # Corpus-wide terms add noise to a sparse query and should not dominate ranking.
    "ai", "nist", "rmf", "framework", "profile",
}
RETRIEVAL_VERSION = "fts5-rrf-source-filter-snapshot-v2"


def _fts_query(question: str) -> str:
    # FTS syntax is not exposed directly: only word-like terms are accepted.
    terms = [
        term for term in re.findall(r"[A-Za-z0-9_]{2,}", question.lower()) if term not in STOPWORDS
    ]
    return " OR ".join(terms[:20])


def _query_terms(question: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[A-Za-z0-9_]{2,}", question.lower())
        if term not in STOPWORDS
    }


class HybridRetriever:
    """RRF combines deterministic FTS with an optional semantic retriever.

    The semantic layer is intentionally optional so a reviewer can run the project
    without a GPU or model download. Install `.[semantic]` to enable it.
    """

    def __init__(self, db: Database):
        self.db = db
        self._semantic_model = None
        self._semantic_model_name: str | None = None

    def active_document_ids(self, as_of: date | None, document_ids: list[int] | None = None) -> list[int]:
        """Default to one latest snapshot per source. Explicit IDs pin versions.

        as_of refers to publication date, not proof of historical availability.
        Undated sources are excluded from dated queries instead of guessed.
        """
        with self.db.connection() as conn:
            rows = conn.execute("""SELECT id, source_uri, effective_from, retrieved_at
                FROM documents ORDER BY COALESCE(effective_from, substr(retrieved_at, 1, 10), '') DESC, id DESC""").fetchall()
        seen, selected = set(), []
        for row in rows:
            if as_of and (not row["effective_from"] or row["effective_from"] > as_of.isoformat()):
                continue
            if document_ids is not None:
                if row["id"] in document_ids:
                    selected.append(row["id"])
            elif row["source_uri"] not in seen:
                selected.append(row["id"])
                seen.add(row["source_uri"])
        return selected

    def _lexical(self, question: str, as_of: date | None, limit: int, document_ids: list[int] | None = None) -> list[dict]:
        query = _fts_query(question)
        if not query:
            return []
        active = self.active_document_ids(as_of, document_ids)
        if not active:
            return []
        sql = f"""
        SELECT c.id, c.text, c.page_start, c.page_end, d.title, d.source_uri, d.version, d.effective_from,
               d.id AS document_id, d.publisher, d.framework, d.source_sha256, d.source_url,
               bm25(chunks_fts) AS raw_score
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH ?
          AND d.id IN ({','.join('?' for _ in active)})
        ORDER BY raw_score
        LIMIT ?
        """
        with self.db.connection() as conn:
            rows = conn.execute(sql, (query, *active, limit)).fetchall()
        return [dict(row) for row in rows]

    def _semantic(self, question: str, as_of: date | None, limit: int, document_ids: list[int] | None = None) -> list[dict]:
        if not settings.semantic_enabled:
            return []
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError:
            return []
        if self._semantic_model is None or self._semantic_model_name != settings.semantic_model:
            self._semantic_model = SentenceTransformer(settings.semantic_model)
            self._semantic_model_name = settings.semantic_model
        active = self.active_document_ids(as_of, document_ids)
        if not active:
            return []
        with self.db.connection() as conn:
            rows = conn.execute(
                f"""SELECT c.id, c.text, c.page_start, c.page_end, d.title, d.source_uri, d.version, d.effective_from,
                d.id AS document_id, d.publisher, d.framework, d.source_sha256, d.source_url
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE d.id IN ({','.join('?' for _ in active)})""",
                active,
            ).fetchall()
        if not rows:
            return []
        chunk_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in chunk_ids)
        with self.db.connection() as conn:
            cached = {
                row["chunk_id"]: row
                for row in conn.execute(
                    f"SELECT chunk_id, dimension, vector FROM embeddings WHERE model = ? AND chunk_id IN ({placeholders})",
                    (settings.semantic_model, *chunk_ids),
                ).fetchall()
            }
            missing = [row for row in rows if row["id"] not in cached]
            if missing:
                vectors = self._semantic_model.encode(
                    [row["text"] for row in missing], convert_to_numpy=True, normalize_embeddings=True
                ).astype(np.float32)
                for row, vector in zip(missing, vectors, strict=True):
                    conn.execute(
                        "INSERT OR REPLACE INTO embeddings (chunk_id, model, dimension, vector) VALUES (?, ?, ?, ?)",
                        (row["id"], settings.semantic_model, len(vector), vector.tobytes()),
                    )
                    cached[row["id"]] = {"dimension": len(vector), "vector": vector.tobytes()}
        question_vector = self._semantic_model.encode(
            question, convert_to_numpy=True, normalize_embeddings=True
        ).astype(np.float32)
        scores = [
            float(question_vector @ np.frombuffer(cached[row["id"]]["vector"], dtype=np.float32))
            for row in rows
        ]
        ordered = sorted(zip(rows, scores), key=lambda pair: pair[1], reverse=True)[:limit]
        return [{**dict(row), "semantic_score": float(score)} for row, score in ordered]

    def warm_semantic_index(self, as_of: date | None = None) -> int:
        """Populate the local embedding cache; returns the number of active chunks."""
        self._semantic("semantic index warmup", as_of, 1)
        as_of_value = as_of.isoformat() if as_of else "9999-12-31"
        with self.db.connection() as conn:
            return conn.execute(
                """SELECT COUNT(*) FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE d.effective_from IS NULL OR d.effective_from <= ?""",
                (as_of_value,),
            ).fetchone()[0]

    def search(self, question: str, as_of: date | None, top_k: int, document_ids: list[int] | None = None) -> list[RetrievedChunk]:
        content_question = question
        # Explicit source names are scope signals. Aliases come from the curated
        # catalog, not benchmark questions; shorter overlapping aliases lose to
        # longer names (e.g. AI RMF vs AI RMF Playbook).
        if document_ids is None:
            lower = question.lower()
            matches = []
            for document in self.db.catalog():
                for alias in json.loads(document["search_aliases"]):
                    match = re.search(r"\b" + re.escape(alias.lower()) + r"\b", lower)
                    if match:
                        matches.append((document["id"], match.start(), match.end()))
            if matches:
                document_ids = [doc_id for doc_id, start, end in matches
                                if not any(a <= start and b >= end and (b-a) > (end-start) for _, a, b in matches)]
                active = set(self.active_document_ids(as_of))
                document_ids = list(set(document_ids) & active)
                for start, end in sorted({(a, b) for _, a, b in matches}, reverse=True):
                    content_question = content_question[:start] + " " * (end-start) + content_question[end:]
                if not _query_terms(content_question):
                    content_question = question
        lexical = self._lexical(content_question, as_of, top_k * 12, document_ids)
        semantic = self._semantic(question, as_of, top_k * 3, document_ids)
        scores: dict[int, float] = defaultdict(float)
        items: dict[int, dict] = {}
        ranks: dict[int, dict] = defaultdict(dict)
        for rank, item in enumerate(lexical, start=1):
            item_id = item["id"]
            items[item_id] = item
            ranks[item_id]["lexical_rank"] = rank
            scores[item_id] += 1 / (60 + rank)
        for rank, item in enumerate(semantic, start=1):
            item_id = item["id"]
            items[item_id] = item
            ranks[item_id]["semantic_rank"] = rank
            scores[item_id] += settings.semantic_rrf_weight / (60 + rank)
        # Source-title overlap is a transparent routing signal. It prevents a
        # corpus-wide word such as "risk" from outranking a document explicitly
        # named in the question (e.g., the Generative AI Profile). It is small
        # enough that it cannot create a result that lexical/semantic search did
        # not already retrieve.
        query_terms = _query_terms(content_question)
        if not query_terms:
            return []
        for item_id, item in items.items():
            title_terms = set(re.findall(r"[A-Za-z0-9_]{2,}", item["title"].lower()))
            scores[item_id] += 0.02 * len(query_terms & title_terms)
            # Tables of contents and boilerplate often match many query terms but
            # contain no explanation. Keep them searchable with a ranking penalty.
            if re.search(r"(?:\.\s*){5,}", item["text"]) or "table of contents" in item["text"].lower():
                scores[item_id] -= 0.025
            if re.search(r"copyright|not subject to copyright|commercial entities", item["text"], re.I):
                scores[item_id] -= 0.01
        # An FTS match alone is not evidence. If no candidate contains at least
        # half of the meaningful query terms, abstain at retrieval time rather
        # than allowing a generic corpus word to manufacture an answer.
        term_coverage = {
            item_id: len(query_terms & set(re.findall(r"[A-Za-z0-9_]{2,}", (item["text"] + " " + item["title"]).lower())))
            / len(query_terms)
            for item_id, item in items.items()
        }
        if not term_coverage or max(term_coverage.values()) < settings.min_term_coverage:
            return []
        # A RAG answer benefits more from five independent pieces of evidence
        # than five adjacent chunks from the same PDF page. Keep one best chunk
        # per source page while preserving global rank order.
        chosen: list[int] = []
        seen_pages: set[tuple[str, int | None]] = set()
        ranked_ids = sorted(scores, key=scores.get, reverse=True)
        if document_ids is None:
            # A broad question needs multiple publishers/frameworks represented.
            # First surface the best passage per document, then fill remaining slots.
            seen_documents = set()
            first, remaining = [], []
            for chunk_id in ranked_ids:
                doc_id = items[chunk_id]["document_id"]
                if doc_id in seen_documents:
                    remaining.append(chunk_id)
                else:
                    first.append(chunk_id)
                    seen_documents.add(doc_id)
            ranked_ids = first + remaining
        for chunk_id in ranked_ids:
            page_key = (str(items[chunk_id]["document_id"]), items[chunk_id]["page_start"] if items[chunk_id]["page_start"] is not None else chunk_id)
            if page_key in seen_pages:
                continue
            seen_pages.add(page_key)
            chosen.append(chunk_id)
            if len(chosen) == top_k:
                break
        return [
            RetrievedChunk(
                citation_id=f"S{index}",
                document_title=items[chunk_id]["title"],
                source_uri=items[chunk_id]["source_uri"],
                version=items[chunk_id]["version"],
                effective_from=items[chunk_id]["effective_from"],
                chunk_id=chunk_id,
                page_start=items[chunk_id]["page_start"],
                page_end=items[chunk_id]["page_end"],
                text=items[chunk_id]["text"],
                lexical_rank=ranks[chunk_id].get("lexical_rank"),
                semantic_rank=ranks[chunk_id].get("semantic_rank"),
                rrf_score=round(scores[chunk_id], 6),
                document_id=items[chunk_id]["document_id"],
                publisher=items[chunk_id]["publisher"], framework=items[chunk_id]["framework"],
                source_sha256=items[chunk_id]["source_sha256"], source_url=items[chunk_id]["source_url"],
            )
            for index, chunk_id in enumerate(chosen, start=1)
        ]
