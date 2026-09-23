from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous|prior) instructions",
    r"reveal (the )?(system|developer) prompt",
    r"disregard (all |the )?rules",
]


def inspect_question(question: str) -> list[str]:
    lowered = question.lower()
    return ["possible_prompt_injection"] if any(re.search(p, lowered) for p in INJECTION_PATTERNS) else []


def citation_coverage(answer: str, citation_ids: list[str]) -> float:
    """A simple, transparent gate: generated answers must use retrieved citations."""
    if not answer.strip():
        return 0.0
    cited = {citation_id for citation_id in citation_ids if f"[{citation_id}]" in answer}
    return round(len(cited) / len(citation_ids), 2) if citation_ids else 0.0


def redact_for_trace(value: str) -> str:
    """Keep common accidental identifiers out of persisted diagnostic traces."""
    value = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]", value)
    return re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]", value)
