"""Publish reproducible retrieval results without private reviews or queries."""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.database import Database
from app.services.retrieval import HybridRetriever
from app.services.evaluation import run_retrieval_evaluation


if __name__ == "__main__":
    db = Database(settings.db_path)
    retriever = HybridRetriever(db)
    active = set(retriever.active_document_ids(None))
    sources = [{k:d[k] for k in ("title","source_uri","version","source_sha256","page_count","chunk_count")}
               for d in db.catalog() if d["id"] in active]
    suites = [run_retrieval_evaluation(retriever, ROOT / "evals" / name).model_dump(mode="json")
              for name in ("nist_golden_set.json", "security_golden_set.json")]
    report = {"generated_at":datetime.now(UTC).isoformat(),"corpus_snapshot":db.snapshot(),
              "documents":len(sources),"pages":sum(d["page_count"] for d in sources),
              "passages":sum(d["chunk_count"] for d in sources),"sources":sources,"evaluations":suites,
              "limits":["Development/regression suites, not held-out validation.",
                        "Source hit-rate and exact-page hits do not measure generated answer accuracy.",
                        "Review discovery is lexical and final coverage decisions require a human."]}
    destination = ROOT / "reports" / "release-v0.2.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(destination)
    for suite in suites:
        print(suite["suite"], {k:suite[k] for k in ("retrieval_recall_at_k","mean_reciprocal_rank","citation_page_recall_at_k","abstention_rate","latency_p95_ms")})
