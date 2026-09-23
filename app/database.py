from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  version TEXT NOT NULL,
  effective_from TEXT,
  trust_tier TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  source_sha256 TEXT,
  retrieved_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  page_start INTEGER,
  page_end INTEGER,
  UNIQUE(document_id, ordinal)
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, title, source_uri, content=''
);
CREATE TABLE IF NOT EXISTS traces (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  event_type TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
  chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  dimension INTEGER NOT NULL,
  vector BLOB NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(chunk_id, model)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Keep local demo databases compatible as provenance fields are added."""
        document_columns = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
        for column, kind in {"source_sha256": "TEXT", "retrieved_at": "TEXT"}.items():
            if column not in document_columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {kind}")
        chunk_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chunks)")}
        for column in ("page_start", "page_end"):
            if column not in chunk_columns:
                conn.execute(f"ALTER TABLE chunks ADD COLUMN {column} INTEGER")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_trace(self, trace_id: str, event_type: str, payload: dict) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO traces (id, event_type, payload) VALUES (?, ?, ?)",
                # Query traces can contain Pydantic fields such as ``date`` from
                # cited sources.  Persist a JSON-safe representation rather than
                # letting an audit-write failure turn a successful retrieval into
                # a 500 response.
                (trace_id, event_type, json.dumps(payload, sort_keys=True, default=str)),
            )

    def get_trace(self, trace_id: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, created_at, event_type, payload FROM traces WHERE id = ?", (trace_id,)
            ).fetchone()
        if not row:
            return None
        return {**dict(row), "payload": json.loads(row["payload"])}

    def get_chunk(self, chunk_id: int) -> dict | None:
        """Return one cited passage together with its source provenance."""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT chunks.id AS chunk_id, chunks.text, chunks.page_start, chunks.page_end,
                       documents.title AS document_title, documents.source_uri, documents.version,
                       documents.effective_from, documents.trust_tier
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                WHERE chunks.id = ?
                """,
                (chunk_id,),
            ).fetchone()
        return dict(row) if row else None
