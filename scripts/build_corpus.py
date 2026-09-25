"""Build immutable, fingerprinted extraction snapshots from the curated manifest.

Usage: python scripts/build_corpus.py
Cached downloads never acquire a fictitious new retrieval date. Refreshes create
new hash-named artifacts; a source's earlier snapshot is never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import sys
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import certifi
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.database import Database
from app.schemas import DocumentIngestRequest
from app.services.ingest import ingest_document


def build(manifest_path: Path, db_path: Path, refresh: bool = False, only: list[str] | None = None) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = Database(db_path)
    records = []
    for source in manifest["sources"]:
        if only and source["id"] not in only:
            continue
        folder = ROOT / "data" / "sources" / source["id"]
        folder.mkdir(parents=True, exist_ok=True)
        pointer = folder / "latest.json"
        if pointer.exists() and not refresh:
            snapshot = json.loads(pointer.read_text(encoding="utf-8"))
        else:
            print(f"Downloading {source['id']}", flush=True)
            request = Request(source["pdf_url"], headers={"User-Agent": "EvidenceTrace/0.2 (portfolio research)"})
            with urlopen(request, context=ssl.create_default_context(cafile=certifi.where()), timeout=45) as response:
                payload = response.read(25_000_001)
            if len(payload) > 25_000_000 or not payload.startswith(b"%PDF"):
                raise ValueError(f"Invalid or oversized PDF: {source['id']}")
            digest = hashlib.sha256(payload).hexdigest()
            if source.get("sha256") and digest != source["sha256"]:
                raise ValueError(f"Publisher bytes changed for {source['id']}; review the publication and update the manifest deliberately")
            raw_path = folder / f"{digest}.pdf"
            if not raw_path.exists():
                raw_path.write_bytes(payload)
            snapshot = {"sha256": digest, "retrieved_at": datetime.now(UTC).isoformat()}
            pointer.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        raw_path = folder / f"{snapshot['sha256']}.pdf"
        if source.get("sha256") and source["sha256"] != snapshot["sha256"]:
            raise ValueError(f"Cached snapshot differs from pinned manifest: {source['id']}")
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != snapshot["sha256"]:
            raise ValueError(f"Cached source hash mismatch: {source['id']}")
        # Collapse layout padding while retaining line breaks and physical pages.
        pages, extraction_notes = [], []
        for number, page in enumerate(PdfReader(raw_path).pages, 1):
            layout = re.sub(r"[ \t]{3,}", "  ", page.extract_text(extraction_mode="layout") or "").strip()
            plain = (page.extract_text() or "").strip()
            # Layout extraction may omit rotated text, especially table pages.
            # Compare non-whitespace content and use plain extraction when needed.
            if len(re.sub(r"\s", "", plain)) > len(re.sub(r"\s", "", layout)) * 1.15:
                pages.append(plain)
                extraction_notes.append({"page": number, "method": "plain-fallback", "reason": "layout omitted text"})
            else:
                pages.append(layout)
            if len(pages[-1]) < 40:
                extraction_notes.append({"page": number, "warning": "little or no extracted text"})
        if sum(len(p) for p in pages) < 500:
            raise ValueError(f"No usable text: {source['id']}; OCR is not enabled")
        processed = ROOT / "data" / "processed" / source["id"]
        processed.mkdir(parents=True, exist_ok=True)
        record = {"source": source, **snapshot, "pages": pages, "extractor": "pypdf-layout-fallback-v3", "extraction_notes": extraction_notes}
        extracted_path = processed / f"{snapshot['sha256']}-layout-v3.json"
        if not extracted_path.exists():
            extracted_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        result = ingest_document(db, DocumentIngestRequest(
            title=source["title"], source_uri=source["source_uri"], source_url=source["pdf_url"],
            content="\n\n".join(pages), pages=pages, version=source["version"],
            effective_from=source.get("published"), trust_tier=source["trust_tier"],
            source_sha256=snapshot["sha256"], retrieved_at=snapshot["retrieved_at"],
            publisher=source["publisher"], framework=source["framework"],
            search_aliases=source.get("search_aliases", []),
        ))
        summary = {"id": source["id"], "pages": len(pages), **snapshot, **result, "extraction_notes": extraction_notes}
        records.append(summary)
        print(json.dumps(summary), flush=True)
    from app.services.retrieval import HybridRetriever
    active = set(HybridRetriever(db).active_document_ids(None))
    report = {"corpus": manifest["corpus_name"], "snapshot": db.snapshot(), "sources": records,
              "documents": len(active), "pages": sum(d["page_count"] for d in db.catalog() if d["id"] in active)}
    output = ROOT / "artifacts" / "corpus"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{report['snapshot']}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "corpus_manifest.json")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "evidencetrace-v0.2.db")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--only", nargs="+")
    args = parser.parse_args()
    print(json.dumps(build(args.manifest, args.db, args.refresh, args.only), indent=2))
