from __future__ import annotations

import json
import time
import math
from statistics import median
from pathlib import Path

from app.schemas import EvaluationCaseResult, EvaluationReport
from app.services.guardrails import inspect_question
from app.services.retrieval import HybridRetriever, RETRIEVAL_VERSION


def run_retrieval_evaluation(retriever: HybridRetriever, suite_path: Path) -> EvaluationReport:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = suite["cases"]
    hits = 0
    answerable = 0
    abstentions = 0
    reciprocal_ranks: list[float] = []
    page_labeled_cases = 0
    page_hits = 0
    case_results: list[EvaluationCaseResult] = []
    latencies = []
    for case in cases:
        started = time.perf_counter()
        # The query path applies this gate before retrieval; evaluation must test
        # the same behavior rather than measuring an unsafe, bypassed code path.
        results = (
            []
            if inspect_question(case["question"])
            else retriever.search(case["question"], None, case.get("top_k", 5))
        )
        source_uris = {result.source_uri for result in results}
        latency = round((time.perf_counter() - started) * 1000, 2)
        latencies.append(latency)
        if case["answerable"]:
            answerable += 1
            hits += int(bool(source_uris & set(case["expected_sources"])))
            rank = next(
                (
                    index
                    for index, result in enumerate(results, start=1)
                    if result.source_uri in set(case["expected_sources"])
                ),
                None,
            )
            reciprocal_ranks.append(1 / rank if rank else 0.0)
            expected_pages = set(case.get("expected_pages", []))
            page_match = any(
                result.source_uri in set(case["expected_sources"])
                and result.page_start in expected_pages
                for result in results
            )
            if expected_pages:
                page_labeled_cases += 1
                page_hits += int(page_match)
            case_results.append(
                EvaluationCaseResult(
                    id=case.get("id", case["question"]),
                    answerable=True,
                    expected_sources=case["expected_sources"],
                    retrieved_sources=[result.source_uri for result in results],
                    reciprocal_rank=1 / rank if rank else 0.0,
                    passed=bool(rank) and (not expected_pages or page_match),
                    retrieved_evidence=[{"source_uri":r.source_uri,"page":r.page_start,"chunk_id":r.chunk_id} for r in results],
                    latency_ms=latency,
                )
            )
        else:
            abstentions += int(not results)
            case_results.append(
                EvaluationCaseResult(
                    id=case.get("id", case["question"]),
                    answerable=False,
                    expected_sources=[],
                    retrieved_sources=[result.source_uri for result in results],
                    passed=not results,
                    retrieved_evidence=[{"source_uri":r.source_uri,"page":r.page_start,"chunk_id":r.chunk_id} for r in results],
                    latency_ms=latency,
                )
            )
    return EvaluationReport(
        suite=suite["name"],
        cases=len(cases),
        retrieval_recall_at_k=round(hits / answerable, 3) if answerable else 0.0,
        mean_reciprocal_rank=round(sum(reciprocal_ranks) / answerable, 3) if answerable else 0.0,
        citation_page_recall_at_k=(
            round(page_hits / page_labeled_cases, 3) if page_labeled_cases else None
        ),
        answerable_cases=answerable,
        abstention_rate=round(abstentions / max(1, len(cases) - answerable), 3),
        notes=[
            "Retrieval-only evaluation. Add answer-quality judging after selecting a model provider.",
            suite.get("labeling", "Project-authored development/regression suite, not an independent held-out benchmark."),
            "Legacy retrieval_recall_at_k is source hit-rate@k (at least one expected source), not passage recall or answer correctness.",
        ],
        case_results=case_results,
        corpus_snapshot=retriever.db.snapshot(), retrieval_version=RETRIEVAL_VERSION,
        latency_p50_ms=round(median(latencies), 2) if latencies else 0,
        latency_p95_ms=sorted(latencies)[max(0, math.ceil(len(latencies)*.95)-1)] if latencies else 0,
    )
