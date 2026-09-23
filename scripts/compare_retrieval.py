"""Benchmark lexical retrieval against weighted semantic-fusion candidates.

This is an experiment runner, not a tuning shortcut: select a configuration only
when it improves the held-out, versioned evaluation suite without weakening
abstention behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import Database
from app.services.evaluation import run_retrieval_evaluation
from app.services.retrieval import HybridRetriever


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, default=Path("evals/nist_golden_set.json"))
    parser.add_argument("--weights", type=float, nargs="+", default=[0.25, 0.5, 0.7, 1.0])
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/experiments"))
    args = parser.parse_args()
    retriever = HybridRetriever(Database(settings.db_path))
    original_enabled = settings.semantic_enabled
    original_weight = settings.semantic_rrf_weight
    candidates = [("lexical", False, 0.0), *[(f"semantic_rrf_{weight}", True, weight) for weight in args.weights]]
    results = []
    try:
        for name, enabled, weight in candidates:
            object.__setattr__(settings, "semantic_enabled", enabled)
            object.__setattr__(settings, "semantic_rrf_weight", weight)
            report = run_retrieval_evaluation(retriever, args.suite)
            row = {
                "name": name,
                "semantic_enabled": enabled,
                "semantic_rrf_weight": weight,
                "recall_at_k": report.retrieval_recall_at_k,
                "mrr": report.mean_reciprocal_rank,
                "page_recall_at_k": report.citation_page_recall_at_k,
                "abstention_rate": report.abstention_rate,
            }
            results.append(row)
            print(row)
    finally:
        object.__setattr__(settings, "semantic_enabled", original_enabled)
        object.__setattr__(settings, "semantic_rrf_weight", original_weight)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / f"retrieval-comparison-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    destination.write_text(json.dumps({"suite": str(args.suite), "results": results}, indent=2), encoding="utf-8")
    print(f"Saved {destination}")


if __name__ == "__main__":
    main()
