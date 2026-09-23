"""AWS Lambda entry point for the public retrieval-only EvidenceTrace demo."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def configure_lambda_database() -> None:
    """Copy the packaged read-only corpus to Lambda's writable temporary disk."""
    packaged_database = Path(__file__).resolve().parents[1] / "data" / "evidencetrace.db"
    runtime_database = Path("/tmp/evidencetrace.db")
    if not runtime_database.exists():
        shutil.copy2(packaged_database, runtime_database)
    os.environ.setdefault("EVIDENCETRACE_DB_PATH", str(runtime_database))


configure_lambda_database()

from mangum import Mangum  # noqa: E402
from app.main import app  # noqa: E402


# API Gateway's managed stage is named ``default``.  Strip that prefix before
# FastAPI routes the request, while keeping Function URL compatibility.
handler = Mangum(app, lifespan="off", api_gateway_base_path="/default")
