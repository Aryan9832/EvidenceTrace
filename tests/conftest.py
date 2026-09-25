"""No test depends on a downloaded corpus, live key, or the developer database."""
import os
import tempfile
from pathlib import Path
import pytest

_session_dir = tempfile.TemporaryDirectory(prefix="evidencetrace-tests-")
os.environ["EVIDENCETRACE_DB_PATH"] = str(Path(_session_dir.name) / "session.db")
os.environ["EVIDENCETRACE_SEMANTIC_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def isolated_api(tmp_path, monkeypatch):
    import app.main as main
    from app.database import Database
    from app.services.ingest import ingest_document
    from app.services.retrieval import HybridRetriever
    from app.schemas import DocumentIngestRequest
    from app.security import RequestLimiter
    database = Database(tmp_path / "api.db")
    page = "The four functions in the AI RMF Core are GOVERN, MAP, MEASURE, and MANAGE. These functions organize risk management."
    ingest_document(database, DocumentIngestRequest(
        title="AI RMF Core", source_uri="https://doi.org/10.6028/NIST.AI.100-1",
        content=page, pages=[page], publisher="NIST", framework="AI RMF"))
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main, "retriever", HybridRetriever(database))
    monkeypatch.setattr(main, "limiter", RequestLimiter(limit=200))
    monkeypatch.setenv("EVIDENCETRACE_OPERATOR_KEY", "test-operator")
    monkeypatch.setenv("EVIDENCETRACE_LOCAL_MODE", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
