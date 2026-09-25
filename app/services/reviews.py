"""Deterministic evidence discovery followed by explicit human adjudication.

The matching score is lexical coverage, never confidence or compliance. Uploaded
text remains outside the shared corpus. Reports persist selected excerpts so the
review can be reproduced and audited without storing the full submission.
"""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from datetime import UTC, datetime

from app.database import Database
from app.schemas import ReviewRequest
from app.services.guardrails import inspect_question, redact_for_trace
from app.services.ingest import _chunks
from app.services.retrieval import HybridRetriever, RETRIEVAL_VERSION

REVIEW_VERSION = "evidence-discovery-human-review-v1"

# These are project-authored review topics, not an official compliance checklist.
# Search queries locate actual primary-source evidence at runtime.
CONTROLS = [
    {"id": "prompt-injection", "title": "Prompt injection boundaries", "frameworks": ["LLM Top 10", "Adversarial ML"],
     "query": "prompt injection instructions external data",
     "signals": ["prompt injection", "untrusted", "instructions", "external content", "input validation"],
     "request": "Provide the trust-boundary design and prompt-injection test results, including attacks through retrieved content."},
    {"id": "sensitive-data", "title": "Sensitive information handling", "frameworks": ["LLM Top 10", "GenAI Profile"],
     "query": "sensitive information privacy disclosure personal data",
     "signals": ["personal data", "pii", "redact", "retention", "sensitive", "privacy"],
     "request": "Provide the data-flow diagram, retention policy, and evidence of redaction and access-control testing."},
    {"id": "human-oversight", "title": "Human oversight and approvals", "frameworks": ["AI RMF", "AI RMF Playbook", "LLM Top 10"],
     "query": "human oversight approval intervention",
     "signals": ["human", "approval", "reviewer", "escalat", "oversight"],
     "request": "Identify who approves consequential actions, the escalation path, and a recorded approval example."},
    {"id": "output-validation", "title": "Output validation and grounding", "frameworks": ["LLM Top 10", "GenAI Profile"],
     "query": "output validation misinformation verification",
     "signals": ["output", "validat", "citation", "ground", "fact-check", "accuracy"],
     "request": "Provide output-validation rules and a labeled test set covering unsupported answers and unsafe outputs."},
    {"id": "supply-chain", "title": "Model and data supply chain", "frameworks": ["SSDF", "SSDF AI Profile", "LLM Top 10"],
     "query": "supply chain provenance third party models data",
     "signals": ["supplier", "third-party", "third party", "provenance", "dependency", "model version", "sbom"],
     "request": "Provide the model/dependency inventory, origin records, version pins, and supplier review evidence."},
    {"id": "monitoring", "title": "Monitoring and incident response", "frameworks": ["AI RMF", "AI RMF Playbook", "GenAI Profile"],
     "query": "monitoring incident response post deployment",
     "signals": ["monitor", "incident", "alert", "rollback", "on-call", "post-deployment"],
     "request": "Provide monitoring thresholds, an incident runbook, rollback steps, and an exercised incident record."},
    {"id": "security-testing", "title": "Adversarial evaluation", "frameworks": ["Adversarial ML", "SSDF AI Profile", "GenAI Profile"],
     "query": "adversarial testing evaluation attacks mitigations",
     "signals": ["adversarial", "red team", "red-team", "attack", "security test", "penetration"],
     "request": "Provide adversarial test cases, threat assumptions, measured results, and unresolved failure categories."},
    {"id": "resource-limits", "title": "Resource consumption limits", "frameworks": ["LLM Top 10"],
     "query": "unbounded consumption rate limits resource",
     "signals": ["rate limit", "budget", "quota", "timeout", "token limit", "resource"],
     "request": "Provide per-user quotas, execution limits, timeout behavior, and cost/load test results."},
]


def internal_candidates(content: str, signals: list[str]) -> list[dict]:
    candidates = []
    passages = [piece for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()
                for piece in _chunks(paragraph.strip(), target_chars=850, overlap_chars=0)]
    for number, passage in enumerate(passages, 1):
        lower = passage.lower()
        matches = [term for term in signals if term in lower]
        if not matches:
            continue
        # These are hints for the reviewer, not a semantic contradiction classifier.
        caution = bool(re.search(r"\b(no|not|never|planned|todo|missing|without|will|future|lack|lacks)\b|n't\b", lower))
        candidates.append({"passage": number, "text": redact_for_trace(passage), "matched_terms": matches,
                           "lexical_coverage": round(len(matches) / len(signals), 3),
                           "caution": "May describe a gap, negation, or future work; inspect the wording." if caution else None})
    return sorted(candidates, key=lambda c: c["lexical_coverage"], reverse=True)[:3]


def create_review(db: Database, retriever: HybridRetriever, request: ReviewRequest) -> dict:
    started = time.perf_counter()
    ids = request.control_ids or [c["id"] for c in CONTROLS]
    unknown = set(ids) - {c["id"] for c in CONTROLS}
    if unknown:
        raise ValueError(f"Unknown review topics: {', '.join(sorted(unknown))}")
    catalog = db.catalog()
    active = set(retriever.active_document_ids(request.as_of))
    findings = []
    for control in CONTROLS:
        if control["id"] not in ids:
            continue
        scope = [d["id"] for d in catalog if d["framework"] in control["frameworks"] and d["id"] in active]
        guidance = retriever.search(control["query"], request.as_of, 3, scope)
        candidates = internal_candidates(request.content, control["signals"])
        status = "needs_review" if candidates else "no_matching_evidence"
        if not guidance:
            status = "guidance_unavailable"
        findings.append({"control_id": control["id"], "title": control["title"],
                         "discovery_status": status, "internal_evidence": candidates,
                         "guidance": [g.model_dump(mode="json") for g in guidance],
                         "suggested_evidence": control["request"], "human_decision": None})
    report = {
        "id": str(uuid.uuid4()), "title": redact_for_trace(request.title), "revision": 1,
        "created_at": datetime.now(UTC).isoformat(), "review_version": REVIEW_VERSION,
        "retrieval_version": RETRIEVAL_VERSION, "corpus_snapshot": db.snapshot(),
        "input_sha256": hashlib.sha256(request.content.encode()).hexdigest(),
        "as_of": str(request.as_of) if request.as_of else None,
        "input_characters": len(request.content),
        "input_flags": inspect_question(request.content), "findings": findings,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "limitations": [
            "Automatic results discover candidate passages; they do not establish implementation, effectiveness, or compliance.",
            "No matching evidence means the submitted text lacks a lexical match, not that the system lacks a control.",
            "Topic mappings are project-authored. A reviewer must assess applicability and make final decisions.",
            "Selected excerpts are retained in this protected report; the full submission is not stored or indexed.",
        ],
    }
    db.save_review(report)
    return report


def compare_reviews(before: dict, after: dict) -> dict:
    old = {f["control_id"]: f for f in before["findings"]}
    changes = []
    for finding in after["findings"]:
        previous = old.pop(finding["control_id"], None)
        changes.append({"control_id": finding["control_id"],
                        "before": previous["discovery_status"] if previous else None,
                        "after": finding["discovery_status"],
                        "evidence_changed": previous is None or previous["internal_evidence"] != finding["internal_evidence"],
                        "guidance_changed": previous is None or previous["guidance"] != finding["guidance"],
                        "decision_changed": previous is None or previous["human_decision"] != finding["human_decision"]})
    changes.extend({"control_id": key, "before": value["discovery_status"], "after": None,
                    "evidence_changed": True, "guidance_changed": True, "decision_changed": True}
                   for key, value in old.items())
    return {"before_id": before["id"], "after_id": after["id"],
            "corpus_changed": before["corpus_snapshot"] != after["corpus_snapshot"], "changes": changes}


def markdown_report(report: dict) -> str:
    # Escape uploaded Markdown/HTML so exported reports cannot inject remote content.
    def safe(value):
        import html
        value = html.escape(str(value))
        return re.sub(r"([\\`*{}_\[\]()#+!|>])", r"\\\1", value)
    lines = [f"# EvidenceTrace review: {safe(report['title'])}", "",
             f"Review: {report['id']} · Revision: {report['revision']}",
             f"Corpus snapshot: {report['corpus_snapshot']}",
             f"Input fingerprint: {report['input_sha256']}", "",
             "Candidate evidence requires human assessment. This is not a compliance certification.", ""]
    for f in report["findings"]:
        lines.extend([f"## {f['title']}", "", f"Discovery: {f['discovery_status']}", ""])
        if f["human_decision"]:
            lines.extend([f"Reviewer decision: {f['human_decision']['status']}", safe(f["human_decision"]["rationale"]), ""])
        for evidence in f["internal_evidence"]:
            lines.extend([f"Submitted passage {evidence['passage']}:", safe(evidence["text"]), ""])
        for g in f["guidance"]:
            lines.extend([f"Guidance: {safe(g['document_title'])}, version {safe(g['version'])}, physical page {g['page_start']}",
                          safe(g["source_uri"]), safe(g["text"]), ""])
        lines.extend([f"Requested evidence: {f['suggested_evidence']}", ""])
    return "\n".join(lines)
