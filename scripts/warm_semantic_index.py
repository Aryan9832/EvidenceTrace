"""Download/load the configured embedding model and build a persistent SQLite cache."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["EVIDENCETRACE_SEMANTIC_ENABLED"] = "true"

from app.config import settings
from app.database import Database
from app.services.retrieval import HybridRetriever


if __name__ == "__main__":
    count = HybridRetriever(Database(settings.db_path)).warm_semantic_index()
    print(f"Cached embeddings for {count} chunks with {settings.semantic_model}.")
