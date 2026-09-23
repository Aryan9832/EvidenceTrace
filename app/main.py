from __future__ import annotations

import time
import uuid
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.config import settings
from app.database import Database
from app.schemas import (
    Answer,
    DocumentIngestRequest,
    EvaluationReport,
    QueryRequest,
    RetrievedChunk,
    SearchRequest,
)
from app.services.evaluation import run_retrieval_evaluation
from app.services.generation import PROMPT_VERSION, generate_answer
from app.services.guardrails import citation_coverage, inspect_question, redact_for_trace
from app.services.ingest import ingest_document
from app.services.retrieval import RETRIEVAL_VERSION, HybridRetriever

app = FastAPI(title="EvidenceTrace", version="0.1.0")
db = Database(settings.db_path)
retriever = HybridRetriever(db)


def nist_pdf_page_url(source_uri: str, page: int | None) -> str | None:
    """Build a page-addressable PDF URL for the NIST AI publications in this demo."""
    prefix = "https://doi.org/10.6028/NIST.AI."
    if not source_uri.startswith(prefix):
        return None
    publication = source_uri.removeprefix("https://doi.org/10.6028/")
    page_fragment = f"#page={page}" if page else ""
    return f"https://nvlpubs.nist.gov/nistpubs/ai/{quote(publication)}.pdf{page_fragment}"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "generation_enabled": bool(settings.openai_api_key)}


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/v1/evidence/{chunk_id}", include_in_schema=False)
def evidence_view(chunk_id: int) -> HTMLResponse:
    """Show a cited passage inside EvidenceTrace when a browser cannot render a PDF."""
    chunk = db.get_chunk(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Evidence passage not found")

    page = chunk["page_start"]
    original_pdf = nist_pdf_page_url(chunk["source_uri"], page) or chunk["source_uri"]
    page_label = f"PDF page {page}" if page else "source page unavailable"
    content = escape(chunk["text"]).replace("\n", "<br>")
    html = f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>EvidenceTrace — cited passage</title><style>
body{{margin:0;background:#f5f7f9;color:#122230;font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif}}main{{max-width:820px;margin:0 auto;padding:44px 24px 72px}}a{{color:#007e70;font-weight:700}}.eyebrow{{color:#007e70;font-size:.76rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase}}h1{{line-height:1.15;margin:8px 0;font-size:clamp(1.6rem,4vw,2.35rem)}}.meta{{color:#687989;margin:0 0 26px}}article{{background:#fff;border:1px solid #dce4e9;border-radius:16px;padding:24px;box-shadow:0 18px 48px rgba(16,39,58,.08)}}blockquote{{margin:0;border-left:4px solid #00a58a;padding-left:18px;color:#294052}}.actions{{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0 0}}.note{{margin-top:25px;color:#687989;font-size:.9rem}}</style></head>
<body><main><a href=\"../../\">← Back to EvidenceTrace</a><p class=\"eyebrow\">Cited evidence</p>
<h1>{escape(chunk['document_title'])}</h1><p class=\"meta\">Version {escape(chunk['version'])} · {page_label} · {escape(chunk['trust_tier'])} source</p>
<article><blockquote>{content}</blockquote><div class=\"actions\"><a href=\"{escape(original_pdf, quote=True)}\" target=\"_blank\" rel=\"noreferrer\">Open original NIST PDF at {page_label} ↗</a><a href=\"{escape(chunk['source_uri'], quote=True)}\" target=\"_blank\" rel=\"noreferrer\">Source record ↗</a></div></article>
<p class=\"note\">This is the exact indexed passage used by EvidenceTrace. The original-PDF link is provided for independent verification.</p></main></body></html>"""
    return HTMLResponse(html)


@app.post("/v1/documents")
def ingest(request: DocumentIngestRequest) -> dict:
    return ingest_document(db, request)


@app.post("/v1/search", response_model=list[RetrievedChunk])
def search(request: SearchRequest) -> list[RetrievedChunk]:
    return retriever.search(request.question, request.as_of, request.top_k)


@app.post("/v1/query", response_model=Answer)
def query(request: QueryRequest) -> Answer:
    started = time.perf_counter()
    flags = inspect_question(request.question)
    trace_id = str(uuid.uuid4())
    if flags:
        answer = Answer(
            answer="I cannot process requests that attempt to override system behavior.",
            status="abstained",
            citations=[],
            trace_id=trace_id,
            citation_coverage=0.0,
            guardrail_flags=flags,
            latency_ms=int((time.perf_counter() - started) * 1000),
            retrieval_version=RETRIEVAL_VERSION,
            prompt_version=None,
        )
    else:
        chunks = retriever.search(request.question, request.as_of, request.top_k)
        if not chunks:
            answer = Answer(
                answer="I do not have enough evidence in the indexed sources to answer that.",
                status="abstained",
                citations=[],
                trace_id=trace_id,
                citation_coverage=0.0,
                guardrail_flags=[],
                latency_ms=int((time.perf_counter() - started) * 1000),
                retrieval_version=RETRIEVAL_VERSION,
                prompt_version=None,
            )
        elif request.generate_answer:
            text, status = generate_answer(request.question, chunks, settings)
            answer = Answer(
                answer=text,
                status=status,
                citations=chunks,
                trace_id=trace_id,
                citation_coverage=citation_coverage(text, [chunk.citation_id for chunk in chunks]),
                guardrail_flags=[],
                latency_ms=int((time.perf_counter() - started) * 1000),
                retrieval_version=RETRIEVAL_VERSION,
                prompt_version=PROMPT_VERSION if status == "answered" else None,
            )
        else:
            answer = Answer(
                answer="Generation disabled at request time; inspect retrieved evidence.",
                status="retrieval_only",
                citations=chunks,
                trace_id=trace_id,
                citation_coverage=0.0,
                guardrail_flags=[],
                latency_ms=int((time.perf_counter() - started) * 1000),
                retrieval_version=RETRIEVAL_VERSION,
                prompt_version=None,
            )
    db.add_trace(
        trace_id,
        "query",
        {"question": redact_for_trace(request.question), "answer": answer.model_dump()},
    )
    return answer


@app.post("/v1/evaluations/demo", response_model=EvaluationReport)
def evaluate_demo() -> EvaluationReport:
    return run_retrieval_evaluation(retriever, Path("evals/demo_golden_set.json"))


@app.get("/v1/traces/{trace_id}")
def get_trace(trace_id: str) -> dict:
    trace = db.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace
