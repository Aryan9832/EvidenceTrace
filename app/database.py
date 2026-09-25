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
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revision INTEGER NOT NULL DEFAULT 1,
  report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_events (
  id INTEGER PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES reviews(id),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  payload TEXT NOT NULL
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
        for column, kind in {
            "source_sha256": "TEXT", "retrieved_at": "TEXT",
            "publisher": "TEXT NOT NULL DEFAULT 'Unknown'",
            "framework": "TEXT NOT NULL DEFAULT 'Other'", "source_url": "TEXT",
            "page_count": "INTEGER NOT NULL DEFAULT 0", "identity_hash": "TEXT",
            "search_aliases": "TEXT NOT NULL DEFAULT '[]'",
            "chunker_version": "TEXT NOT NULL DEFAULT 'legacy'",
        }.items():
            if column not in document_columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {kind}")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS document_identity ON documents(identity_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS document_versions ON documents(source_uri, effective_from)")
        conn.execute("CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id)")
        chunk_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chunks)")}
        for column in ("page_start", "page_end"):
            if column not in chunk_columns:
                conn.execute(f"ALTER TABLE chunks ADD COLUMN {column} INTEGER")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
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
                       documents.effective_from, documents.trust_tier, documents.source_url,
                       documents.source_sha256, documents.publisher, documents.framework,
                       documents.id AS document_id
                FROM chunks
                JOIN documents ON documents.id = chunks.document_id
                WHERE chunks.id = ?
                """,
                (chunk_id,),
            ).fetchone()
        return dict(row) if row else None

    def catalog(self) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT d.*, COUNT(c.id) AS chunk_count FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.id
                GROUP BY d.id ORDER BY d.publisher, d.title, d.effective_from DESC, d.id DESC
            """)]

    def snapshot(self) -> str:
        import hashlib
        with self.connection() as conn:
            rows = conn.execute("SELECT source_uri, version, content_hash, source_sha256, title, framework, search_aliases, effective_from FROM documents ORDER BY source_uri, version, content_hash").fetchall()
        return hashlib.sha256(json.dumps([list(row) for row in rows]).encode()).hexdigest()

    def save_review(self, report: dict) -> None:
        with self.connection() as conn:
            conn.execute("INSERT INTO reviews(id, report) VALUES (?, ?)",
                         (report["id"], json.dumps(report, default=str)))

    def get_review(self, review_id: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute("SELECT report, revision FROM reviews WHERE id = ?", (review_id,)).fetchone()
        return {**json.loads(row["report"]), "revision": row["revision"]} if row else None

    def decide(self, review_id: str, control_id: str, decision: dict) -> dict | None:
        # Optimistic concurrency prevents two reviewers silently overwriting a decision.
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT report, revision FROM reviews WHERE id = ?", (review_id,)).fetchone()
            if not row:
                return None
            if row["revision"] != decision["expected_revision"]:
                raise ValueError("Review changed; reload before saving your decision")
            report = json.loads(row["report"])
            finding = next((f for f in report["findings"] if f["control_id"] == control_id), None)
            if finding is None:
                raise KeyError(control_id)
            finding["human_decision"] = {k: v for k, v in decision.items() if k != "expected_revision"}
            conn.execute("UPDATE reviews SET report = ?, revision = revision + 1 WHERE id = ?",
                         (json.dumps(report), review_id))
            conn.execute("INSERT INTO review_events(review_id, payload) VALUES (?, ?)",
                         (review_id, json.dumps({"control_id": control_id, **decision})))
        return self.get_review(review_id)
