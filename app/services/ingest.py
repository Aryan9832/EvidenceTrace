from __future__ import annotations

import hashlib
import re
from datetime import date

from app.database import Database
from app.schemas import DocumentIngestRequest


def _chunks(text: str, target_chars: int = 900, overlap_chars: int = 160) -> list[str]:
    """Split on paragraph boundaries first, then preserve a small overlap."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    result: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > target_chars:
            result.append(current)
            current = f"{current[-overlap_chars:]}\n\n{paragraph}".strip()
        else:
            current = candidate
    if current:
        result.append(current)
    return result


def _chunks_with_pages(pages: list[str] | None, content: str) -> list[tuple[str, int | None, int | None]]:
    if not pages:
        return [(chunk, None, None) for chunk in _chunks(content)]
    chunks: list[tuple[str, int | None, int | None]] = []
    for page_number, page in enumerate(pages, start=1):
        chunks.extend((chunk, page_number, page_number) for chunk in _chunks(page))
    return chunks


def ingest_document(db: Database, request: DocumentIngestRequest) -> dict:
    content_hash = hashlib.sha256(request.content.encode("utf-8")).hexdigest()
    chunks = _chunks_with_pages(request.pages, request.content)
    with db.connection() as conn:
        existing = conn.execute(
            "SELECT id FROM documents WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            return {"document_id": existing["id"], "status": "unchanged", "chunks": 0}
        cursor = conn.execute(
            """INSERT INTO documents
            (title, source_uri, version, effective_from, trust_tier, content_hash, source_sha256, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request.title,
                request.source_uri,
                request.version,
                request.effective_from.isoformat() if request.effective_from else None,
                request.trust_tier,
                content_hash,
                request.source_sha256,
                request.retrieved_at.isoformat() if request.retrieved_at else None,
            ),
        )
        document_id = cursor.lastrowid
        for ordinal, (chunk_text, page_start, page_end) in enumerate(chunks):
            chunk_cursor = conn.execute(
                "INSERT INTO chunks (document_id, ordinal, text, page_start, page_end) VALUES (?, ?, ?, ?, ?)",
                (document_id, ordinal, chunk_text, page_start, page_end),
            )
            conn.execute(
                "INSERT INTO chunks_fts(rowid, text, title, source_uri) VALUES (?, ?, ?, ?)",
                (chunk_cursor.lastrowid, chunk_text, request.title, request.source_uri),
            )
    return {"document_id": document_id, "status": "ingested", "chunks": len(chunks)}
