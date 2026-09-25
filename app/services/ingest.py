from __future__ import annotations

import hashlib
import re
import json

from app.database import Database
from app.schemas import DocumentIngestRequest

CHUNKER_VERSION = "paragraph-bounded-v2"


def _chunks(text: str, target_chars: int = 900, overlap_chars: int = 160) -> list[str]:
    """Split on paragraph boundaries first, then preserve a small overlap."""
    # PDF extraction often produces one very long paragraph. Bound every chunk,
    # splitting at whitespace when possible, so context windows stay predictable.
    paragraphs = []
    for raw in re.split(r"\n\s*\n", text):
        raw = raw.strip()
        while len(raw) > target_chars:
            cut = raw.rfind(" ", target_chars // 2, target_chars)
            cut = cut if cut > 0 else target_chars
            paragraphs.append(raw[:cut])
            raw = raw[max(1, cut - overlap_chars):].strip()
        if raw:
            paragraphs.append(raw)
    result: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > target_chars:
            result.append(current)
            prefix = current[-overlap_chars:] if overlap_chars > 0 and len(paragraph) + overlap_chars + 2 <= target_chars else ""
            # A pre-split long paragraph already carries its overlap. Do not
            # prepend the same trailing passage twice within the new chunk.
            if prefix and paragraph.startswith(prefix.strip()):
                prefix = ""
            current = f"{prefix}\n\n{paragraph}".strip()
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
    identity_hash = hashlib.sha256(json.dumps({
        "uri": request.source_uri, "version": request.version,
        "effective_from": str(request.effective_from), "content": content_hash,
        "pages": request.pages,
        "chunker": CHUNKER_VERSION,
    }, sort_keys=True).encode()).hexdigest()
    chunks = _chunks_with_pages(request.pages, request.content)
    with db.connection() as conn:
        existing = conn.execute(
            "SELECT id FROM documents WHERE identity_hash = ? OR (identity_hash IS NULL AND content_hash = ? AND source_uri = ? AND version = ? AND effective_from IS ?)",
            (identity_hash, content_hash, request.source_uri, request.version, request.effective_from.isoformat() if request.effective_from else None),
        ).fetchone()
        if existing:
            conn.execute("UPDATE documents SET publisher=?, framework=?, source_url=?, search_aliases=?, page_count=?, source_sha256=COALESCE(?,source_sha256), retrieved_at=COALESCE(retrieved_at,?) WHERE id=?",
                         (request.publisher, request.framework, request.source_url, json.dumps(request.search_aliases),
                          len(request.pages) if request.pages else 0, request.source_sha256,
                          request.retrieved_at.isoformat() if request.retrieved_at else None, existing["id"]))
            return {"document_id": existing["id"], "status": "unchanged", "chunks": 0}
        cursor = conn.execute(
            """INSERT INTO documents
            (title, source_uri, version, effective_from, trust_tier, content_hash, source_sha256, retrieved_at,
             publisher, framework, source_url, page_count, identity_hash, search_aliases, chunker_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request.title,
                request.source_uri,
                request.version,
                request.effective_from.isoformat() if request.effective_from else None,
                request.trust_tier,
                # The legacy schema has a UNIQUE constraint on content_hash.
                # Scope this legacy key to identity; raw bytes remain source_sha256.
                identity_hash,
                request.source_sha256,
                request.retrieved_at.isoformat() if request.retrieved_at else None,
                request.publisher, request.framework, request.source_url,
                len(request.pages) if request.pages else 0, identity_hash, json.dumps(request.search_aliases), CHUNKER_VERSION,
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
