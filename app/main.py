from __future__ import annotations

import time
import uuid
import io
import json
import os
from html import escape
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Database
from app.schemas import (
    Answer,
    DocumentIngestRequest,
    EvaluationReport,
    QueryRequest,
    RetrievedChunk,
    SearchRequest,
    ReviewRequest, ReviewDecision, ReviewComparison,
)
from app.services.evaluation import run_retrieval_evaluation
from app.services.generation import PROMPT_VERSION, generate_answer
from app.services.guardrails import citation_coverage, inspect_question, redact_for_trace
from app.services.ingest import ingest_document
from app.services.retrieval import RETRIEVAL_VERSION, HybridRetriever
from app.services.reviews import CONTROLS, create_review, markdown_report, compare_reviews
from app.services.catalog import compare_sources
from app.security import require_operator, RequestLimiter, BodySizeLimit

app = FastAPI(title="EvidenceTrace", version="0.2.0")
app.add_middleware(BodySizeLimit)
app.mount("/assets", StaticFiles(directory=Path(__file__).parent / "static"), name="assets")
db = Database(settings.db_path)
retriever = HybridRetriever(db)
limiter = RequestLimiter()


@app.middleware("http")
async def request_limits(request: Request, call_next):
    if request.method == "POST" and request.url.path in {"/v1/query", "/v1/search", "/v1/reviews", "/v1/documents/extract"}:
        # Intentionally do not trust forwarded-for supplied by an arbitrary client.
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):
            return JSONResponse({"detail": "Request limit reached; retry in a minute."}, status_code=429, headers={"Retry-After": "60"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    if request.url.path.startswith(("/v1/reviews", "/v1/traces", "/v1/documents/extract")):
        response.headers["Cache-Control"] = "no-store"
    return response


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
    return {"status": "ok", "version": "0.2.0", "generation_enabled": settings.generation_enabled,
            "semantic_enabled": settings.semantic_enabled, "local_mode": settings.local_mode,
            # Lambda exposes a public research experience. Traces are private because
            # they can contain request metadata, so only advertise them when the
            # current deployment has an operator access path.
            "trace_enabled": bool(settings.operator_key or settings.local_mode),
            "review_enabled": bool(settings.operator_key or settings.local_mode) and not bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME")),
            "storage": "ephemeral" if str(settings.db_path).startswith("/tmp/") else "filesystem"}


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "workspace.html")


@app.get("/v1/evidence/{chunk_id}", include_in_schema=False)
def evidence_view(chunk_id: int) -> HTMLResponse:
    """Show a cited passage inside EvidenceTrace when a browser cannot render a PDF."""
    chunk = db.get_chunk(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Evidence passage not found")

    page = chunk["page_start"]
    original_pdf = chunk.get("source_url") or nist_pdf_page_url(chunk["source_uri"], page) or chunk["source_uri"]
    if page and "#page=" not in original_pdf:
        original_pdf += f"#page={page}"
    if urlsplit(original_pdf).scheme not in {"http", "https"}:
        original_pdf = "#"
    safe_source_uri = chunk["source_uri"] if urlsplit(chunk["source_uri"]).scheme in {"http", "https"} else "#"
    page_label = f"PDF page {page}" if page else "source page unavailable"
    content = escape(chunk["text"]).replace("\n", "<br>")
    html = f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>EvidenceTrace — cited passage</title><style>
body{{margin:0;background:#f5f7f9;color:#122230;font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif}}main{{max-width:820px;margin:0 auto;padding:44px 24px 72px}}a{{color:#007e70;font-weight:700}}.eyebrow{{color:#007e70;font-size:.76rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase}}h1{{line-height:1.15;margin:8px 0;font-size:clamp(1.6rem,4vw,2.35rem)}}.meta{{color:#687989;margin:0 0 26px}}article{{background:#fff;border:1px solid #dce4e9;border-radius:16px;padding:24px;box-shadow:0 18px 48px rgba(16,39,58,.08)}}blockquote{{margin:0;border-left:4px solid #00a58a;padding-left:18px;color:#294052}}.actions{{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0 0}}.note{{margin-top:25px;color:#687989;font-size:.9rem}}</style></head>
<body><main><a href=\"../../\">← Back to EvidenceTrace</a><p class=\"eyebrow\">Cited evidence</p>
<h1>{escape(chunk['document_title'])}</h1><p class=\"meta\">Version {escape(chunk['version'])} · {page_label} · {escape(chunk['trust_tier'])} source</p>
<article><blockquote>{content}</blockquote><div class=\"actions\"><a href=\"{escape(original_pdf, quote=True)}\" target=\"_blank\" rel=\"noreferrer\">Open original publication at {page_label} ↗</a><a href=\"{escape(safe_source_uri, quote=True)}\" target=\"_blank\" rel=\"noreferrer\">Source record ↗</a></div></article>
<p class=\"note\">This is the exact indexed passage used by EvidenceTrace. The original-PDF link is provided for independent verification.</p></main></body></html>"""
    return HTMLResponse(html)


@app.post("/v1/documents", dependencies=[Depends(require_operator)])
def ingest(request: DocumentIngestRequest) -> dict:
    return ingest_document(db, request)


@app.post("/v1/search", response_model=list[RetrievedChunk])
def search(request: SearchRequest) -> list[RetrievedChunk]:
    return retriever.search(request.question, request.as_of, request.top_k, request.document_ids)


@app.post("/v1/query", response_model=Answer)
def query(request: QueryRequest, http_request: Request) -> Answer:
    # Paid provider calls require operator access even when public search is enabled.
    if request.generate_answer and settings.generation_enabled:
        require_operator(http_request)
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
        chunks = retriever.search(request.question, request.as_of, request.top_k, request.document_ids)
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
        {"question": redact_for_trace(request.question), "answer": answer.model_dump(),
         "document_ids": request.document_ids, "as_of": request.as_of, "corpus_snapshot": db.snapshot()},
    )
    return answer


@app.post("/v1/evaluations/demo", response_model=EvaluationReport, dependencies=[Depends(require_operator)])
def evaluate_demo() -> EvaluationReport:
    return run_retrieval_evaluation(retriever, Path("evals/demo_golden_set.json"))


@app.get("/v1/traces/{trace_id}", dependencies=[Depends(require_operator)])
def get_trace(trace_id: str) -> dict:
    trace = db.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@app.get("/v1/sources")
def sources() -> dict:
    catalog = db.catalog()
    active = set(retriever.active_document_ids(None))
    return {"snapshot": db.snapshot(), "documents": [{**d, "active": d["id"] in active} for d in catalog],
            "total_pages": sum(d["page_count"] for d in catalog if d["id"] in active),
            "total_chunks": sum(d["chunk_count"] for d in catalog if d["id"] in active)}


@app.get("/v1/sources/compare")
def source_comparison(before: int, after: int) -> dict:
    try:
        return compare_sources(db, before, after)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/review-topics")
def review_topics() -> list[dict]:
    return CONTROLS


@app.get("/v1/examples/design")
def example_design() -> dict:
    path = Path(__file__).resolve().parents[1] / "data" / "demo" / "support_assistant_design.md"
    return {"title": "Helpdesk Copilot — design review", "content": path.read_text(encoding="utf-8")}


@app.post("/v1/documents/extract", dependencies=[Depends(require_operator)])
async def extract_upload(request: Request) -> dict:
    from pypdf import PdfReader
    payload = bytearray()
    async for piece in request.stream():
        payload.extend(piece)
        if len(payload) > 3_000_000:
            raise HTTPException(413, "Upload is limited to 3 MB")
    try:
        if payload.startswith(b"%PDF"):
            reader = PdfReader(io.BytesIO(payload))
            if reader.is_encrypted or len(reader.pages) > 100:
                raise ValueError("Use an unencrypted PDF with at most 100 pages")
            pages = []
            for page in reader.pages:
                pages.append((page.extract_text() or "").strip())
                if sum(map(len, pages)) > 150_000:
                    raise ValueError("Extracted text exceeds 150,000 characters")
            content = "\n\n".join(pages)
            page_count = len(pages)
        else:
            content = payload.decode("utf-8-sig")
            page_count = None
        if not 100 <= len(content) <= 150_000:
            raise ValueError("Need 100–150,000 characters of text. Scanned PDFs need OCR before upload.")
    except Exception as exc:
        raise HTTPException(422, "Unable to extract usable text. Use UTF-8 text/Markdown or an unencrypted text PDF (≤100 pages, ≤150,000 characters).") from exc
    return {"content": content, "pages": page_count, "stored": False}


@app.post("/v1/reviews", dependencies=[Depends(require_operator)])
def review(request: ReviewRequest) -> dict:
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        raise HTTPException(503, "Private reviews require persistent storage. This Lambda deployment is a public research preview.")
    try:
        return create_review(db, retriever, request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/reviews", dependencies=[Depends(require_operator)])
def review_history() -> list[dict]:
    with db.connection() as conn:
        rows = conn.execute("SELECT id, created_at, revision, json_extract(report, '$.title') AS title FROM reviews ORDER BY created_at DESC, rowid DESC LIMIT 50").fetchall()
    return [dict(row) for row in rows]


@app.post("/v1/reviews/compare", dependencies=[Depends(require_operator)])
def review_comparison(request: ReviewComparison) -> dict:
    before, after = db.get_review(request.before_id), db.get_review(request.after_id)
    if not before or not after:
        raise HTTPException(404, "Review not found")
    return compare_reviews(before, after)


@app.get("/v1/reviews/{review_id}", dependencies=[Depends(require_operator)])
def get_review(review_id: str) -> dict:
    report = db.get_review(review_id)
    if not report:
        raise HTTPException(404, "Review not found")
    return report


@app.patch("/v1/reviews/{review_id}/findings/{control_id}", dependencies=[Depends(require_operator)])
def review_decision(review_id: str, control_id: str, request: ReviewDecision) -> dict:
    try:
        report = db.decide(review_id, control_id, request.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, "Review topic not found") from exc
    if not report:
        raise HTTPException(404, "Review not found")
    return report


@app.get("/v1/reviews/{review_id}/events", dependencies=[Depends(require_operator)])
def review_events(review_id: str) -> list[dict]:
    get_review(review_id)
    with db.connection() as conn:
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in conn.execute(
            "SELECT created_at, payload FROM review_events WHERE review_id = ? ORDER BY id", (review_id,))]


@app.get("/v1/reviews/{review_id}/export", dependencies=[Depends(require_operator)])
def export_review(review_id: str, format: str = "markdown") -> Response:
    report = get_review(review_id)
    if format == "json":
        return Response(json.dumps(report, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="review-{report["id"]}.json"'})
    if format != "markdown":
        raise HTTPException(422, "Choose markdown or json")
    return Response(markdown_report(report), media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="review-{report["id"]}.md"'})
