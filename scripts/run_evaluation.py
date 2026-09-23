"""Run a retrieval suite and save a timestamped, reviewable JSON report."""

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
    parser.add_argument("suite", type=Path, nargs="?", default=Path("evals/nist_golden_set.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/evaluations"))
    args = parser.parse_args()
    report = run_retrieval_evaluation(HybridRetriever(Database(settings.db_path)), args.suite)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = args.output_dir / f"{args.suite.stem}-{stamp}.json"
    destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(destination)
    print(
        f"Recall@k={report.retrieval_recall_at_k} | MRR={report.mean_reciprocal_rank} | "
        f"page recall={report.citation_page_recall_at_k} | abstention={report.abstention_rate}"
    )


if __name__ == "__main__":
    main()
