"""Ingest a UTF-8 Markdown or text document into EvidenceTrace.

Example:
python scripts/ingest_file.py data/demo/change_control_policy.md \
  --title "Synthetic Change Control Policy" --source-uri demo://change-control-policy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import Database
from app.schemas import DocumentIngestRequest
from app.services.ingest import ingest_document


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a text document into EvidenceTrace")
    parser.add_argument("file", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--version", default="1.0")
    parser.add_argument("--effective-from")
    parser.add_argument("--trust-tier", default="official", choices=["official", "reviewed", "unverified"])
    args = parser.parse_args()

    document = DocumentIngestRequest(
        title=args.title,
        source_uri=args.source_uri,
        content=args.file.read_text(encoding="utf-8"),
        version=args.version,
        effective_from=args.effective_from,
        trust_tier=args.trust_tier,
    )
    print(ingest_document(Database(settings.db_path), document))


if __name__ == "__main__":
    main()
