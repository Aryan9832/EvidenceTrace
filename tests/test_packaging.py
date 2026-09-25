import importlib.util
from pathlib import Path
from app.database import Database
from app.schemas import DocumentIngestRequest, ReviewRequest
from app.services.ingest import ingest_document
from app.services.reviews import create_review
from app.services.retrieval import HybridRetriever


def test_release_database_excludes_private_material(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "package_release.py"
    spec = importlib.util.spec_from_file_location("package_release", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    database = Database(tmp_path / "private.db")
    content = "Rate limits and quotas bound resource consumption for users. " * 3
    ingest_document(database, DocumentIngestRequest(title="Public guidance", content=content,
        source_uri="https://example.org/guidance", framework="LLM Top 10"))
    create_review(database, HybridRetriever(database), ReviewRequest(title="Private customer review", content=content))
    database.add_trace("private-request", "query", {"private":"do not publish"})
    output = tmp_path / "public.db"
    module.public_database(database.path, output)
    public = Database(output)
    assert public.snapshot() == database.snapshot()
    assert HybridRetriever(public).search("rate limits", None, 3)
    with public.connection() as conn:
        for table in ("reviews", "review_events", "traces"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
