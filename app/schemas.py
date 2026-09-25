from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator, field_validator
from urllib.parse import urlsplit


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
    publisher: str = Field(default="Unknown", max_length=100)
    framework: str = Field(default="Other", max_length=100)
    source_url: str | None = Field(default=None, max_length=1000)
    search_aliases: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("source_uri", "source_url")
    @classmethod
    def safe_uri(cls, value):
        if value is not None and urlsplit(value).scheme not in {"https", "http", "test", "demo"}:
            raise ValueError("Source must use an http(s), test, or demo URI")
        return value

    @model_validator(mode="after")
    def validate_pages(self):
        if self.pages is not None:
            if not self.pages or len(self.pages) > 1500:
                raise ValueError("Supply 1–1500 pages")
            if sum(map(len, self.pages)) > 2_000_000:
                raise ValueError("Page text exceeds 2 MB")
            if self.content != "\n\n".join(self.pages):
                raise ValueError("content must equal pages joined by two newlines")
        return self


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
    document_id: int | None = None
    publisher: str = "Unknown"
    framework: str = "Other"
    source_sha256: str | None = None
    source_url: str | None = None


class QueryRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1_000)
    as_of: date | None = None
    top_k: int = Field(default=6, ge=1, le=12)
    generate_answer: bool = True
    document_ids: list[int] | None = Field(default=None, max_length=100)


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
    document_ids: list[int] | None = Field(default=None, max_length=100)


class ReviewRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=100, max_length=150_000)
    control_ids: list[str] | None = Field(default=None, min_length=1, max_length=12)
    as_of: date | None = None


class ReviewDecision(BaseModel):
    status: Literal["documented", "partially_documented", "insufficient_evidence", "not_applicable"]
    rationale: str = Field(min_length=10, max_length=2000)
    expected_revision: int = Field(ge=1)


class ReviewComparison(BaseModel):
    before_id: str
    after_id: str


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
    corpus_snapshot: str | None = None
    retrieval_version: str | None = None
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None


class EvaluationCaseResult(BaseModel):
    id: str
    answerable: bool
    expected_sources: list[str]
    retrieved_sources: list[str]
    reciprocal_rank: float | None = None
    passed: bool
    retrieved_evidence: list[dict] = Field(default_factory=list)
    latency_ms: float | None = None
