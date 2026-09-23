"""Fetch, fingerprint, extract, and optionally ingest the two fixed NIST PDFs.

The source PDFs are intentionally not committed. This script makes every corpus
snapshot reproducible and records both the PDF hash and its retrieval time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import certifi

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader

from app.config import settings
from app.database import Database
from app.schemas import DocumentIngestRequest
from app.services.ingest import ingest_document

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "corpus_manifest.json"
SOURCE_DIR = ROOT / "data" / "sources"
PROCESSED_DIR = ROOT / "data" / "processed"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "EvidenceTrace/0.1 research project"})
    # Use certifi's maintained CA bundle; do not disable TLS verification for corpus data.
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=60, context=context) as response:
        payload = response.read()
    destination.write_bytes(payload)


def extract_pdf(pdf_path: Path) -> list[str]:
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text(extraction_mode="layout") or ""
        pages.append(text.strip())
    return pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ingest", action="store_true", help="Load extracted documents into the local database")
    parser.add_argument("--refresh", action="store_true", help="Download fresh source PDFs even if cached")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_time = datetime.now(UTC).isoformat()
    for source in manifest["sources"]:
        if "pdf_url" not in source:
            continue
        pdf_path = SOURCE_DIR / f"{source['id']}.pdf"
        if args.refresh or not pdf_path.exists():
            print(f"Downloading {source['id']}...")
            fetch(source["pdf_url"], pdf_path)
        pages = extract_pdf(pdf_path)
        record = {
            "source": source,
            "pdf_path": str(pdf_path.relative_to(ROOT)),
            "retrieved_at": snapshot_time,
            "pdf_sha256": sha256(pdf_path),
            "pages": pages,
        }
        output = PROCESSED_DIR / f"{source['id']}.json"
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Extracted {len(pages)} pages -> {output.relative_to(ROOT)}")
        if args.ingest:
            content = "\n\n".join(pages)
            result = ingest_document(
                Database(settings.db_path),
                DocumentIngestRequest(
                    title=source["title"],
                    source_uri=source["source_uri"],
                    content=content,
                    pages=pages,
                    version=source["version"],
                    effective_from=source["published"],
                    trust_tier=source["trust_tier"],
                    source_sha256=record["pdf_sha256"],
                    retrieved_at=snapshot_time,
                ),
            )
            print(f"Ingestion: {result}")


if __name__ == "__main__":
    main()
