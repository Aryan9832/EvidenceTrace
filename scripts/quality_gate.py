"""Fail a build when a labeled retrieval benchmark regresses below its baseline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import Database
from app.services.evaluation import run_retrieval_evaluation
from app.services.retrieval import HybridRetriever


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", type=Path, default=Path("evals/nist_golden_set.json"))
    parser.add_argument("--min-recall", type=float, default=0.90)
    parser.add_argument("--min-mrr", type=float, default=0.80)
    parser.add_argument("--min-page-recall", type=float, default=0.50)
    parser.add_argument("--min-abstention", type=float, default=0.75)
    args = parser.parse_args()
    report = run_retrieval_evaluation(HybridRetriever(Database(settings.db_path)), args.suite)
    observed = {
        "recall": report.retrieval_recall_at_k,
        "mrr": report.mean_reciprocal_rank,
        "page_recall": report.citation_page_recall_at_k or 0.0,
        "abstention": report.abstention_rate,
    }
    expected = {
        "recall": args.min_recall,
        "mrr": args.min_mrr,
        "page_recall": args.min_page_recall,
        "abstention": args.min_abstention,
    }
    failed = {name: (observed[name], threshold) for name, threshold in expected.items() if observed[name] < threshold}
    print("observed:", observed)
    if failed:
        raise SystemExit(f"Quality gate failed: {failed}")
    print("Quality gate passed.")


if __name__ == "__main__":
    main()
