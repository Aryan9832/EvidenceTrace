from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from app.database import Database
from app.config import settings
from app.schemas import RetrievedChunk

STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "by", "does", "for", "from", "how", "in",
    "is", "it", "of", "on", "or", "say", "the", "to", "was", "what", "when", "where", "which", "who",
    "why", "will", "with",
    # Corpus-wide terms add noise to a sparse query and should not dominate ranking.
    "ai", "nist", "rmf", "framework", "profile",
}
RETRIEVAL_VERSION = "fts5-rrf-title-route-page-diversity-v1"


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

    def _lexical(self, question: str, as_of: date | None, limit: int) -> list[dict]:
        query = _fts_query(question)
        if not query:
            return []
        as_of_value = as_of.isoformat() if as_of else "9999-12-31"
        sql = """
        SELECT c.id, c.text, c.page_start, c.page_end, d.title, d.source_uri, d.version, d.effective_from,
               bm25(chunks_fts) AS raw_score
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH ?
          AND (d.effective_from IS NULL OR d.effective_from <= ?)
        ORDER BY raw_score
        LIMIT ?
        """
        with self.db.connection() as conn:
            rows = conn.execute(sql, (query, as_of_value, limit)).fetchall()
        return [dict(row) for row in rows]

    def _semantic(self, question: str, as_of: date | None, limit: int) -> list[dict]:
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
        as_of_value = as_of.isoformat() if as_of else "9999-12-31"
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT c.id, c.text, c.page_start, c.page_end, d.title, d.source_uri, d.version, d.effective_from
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE d.effective_from IS NULL OR d.effective_from <= ?""",
                (as_of_value,),
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

    def search(self, question: str, as_of: date | None, top_k: int) -> list[RetrievedChunk]:
        lexical = self._lexical(question, as_of, top_k * 3)
        semantic = self._semantic(question, as_of, top_k * 3)
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
        query_terms = _query_terms(question)
        if not query_terms:
            return []
        for item_id, item in items.items():
            title_terms = set(re.findall(r"[A-Za-z0-9_]{2,}", item["title"].lower()))
            scores[item_id] += 0.02 * len(query_terms & title_terms)
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
        for chunk_id in sorted(scores, key=scores.get, reverse=True):
            page_key = (items[chunk_id]["source_uri"], items[chunk_id]["page_start"])
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
            )
            for index, chunk_id in enumerate(chosen, start=1)
        ]
