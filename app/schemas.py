from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field


class DocumentIngestRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    source_uri: str = Field(min_length=3, max_length=500)
    content: str = Field(min_length=100, max_length=2_000_000)
    pages: list[str] | None = None
    version: str = Field(default="1.0", max_length=50)
    effective_from: date | None = None
    trust_tier: Literal["official", "reviewed", "unverified"] = "official"
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    retrieved_at: datetime | None = None


class RetrievedChunk(BaseModel):
    citation_id: str
    document_title: str
    source_uri: str
    version: str
    effective_from: date | None
    chunk_id: int
    page_start: int | None = None
    page_end: int | None = None
    text: str
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    rrf_score: float


class QueryRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1_000)
    as_of: date | None = None
    top_k: int = Field(default=6, ge=1, le=12)
    generate_answer: bool = True


class Answer(BaseModel):
    answer: str
    status: Literal["answered", "abstained", "retrieval_only"]
    citations: list[RetrievedChunk]
    trace_id: str
    citation_coverage: float
    guardrail_flags: list[str]
    latency_ms: int
    retrieval_version: str
    prompt_version: str | None = None


class SearchRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1_000)
    as_of: date | None = None
    top_k: int = Field(default=6, ge=1, le=12)


class EvaluationReport(BaseModel):
    suite: str
    cases: int
    retrieval_recall_at_k: float
    mean_reciprocal_rank: float
    citation_page_recall_at_k: float | None = None
    answerable_cases: int
    abstention_rate: float
    notes: list[str]
    case_results: list["EvaluationCaseResult"] = []


class EvaluationCaseResult(BaseModel):
    id: str
    answerable: bool
    expected_sources: list[str]
    retrieved_sources: list[str]
    reciprocal_rank: float | None = None
    passed: bool
