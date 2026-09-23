# EvidenceTrace

**A version-aware, evidence-first RAG service for NIST AI-risk guidance.** It is
designed to make unsupported answers visible rather than hide them behind a chat
interface.

**Live demo:** https://7sg5kts66a.execute-api.us-east-2.amazonaws.com/default/

The public deployment contains a page-addressable snapshot of NIST AI RMF 1.0 and
the NIST Generative AI Profile. It retrieves the relevant passage, displays the
indexed source text and PDF page, and records a reviewable request trace.

The intended corpus is defined in [`data/corpus_manifest.json`](data/corpus_manifest.json):
NIST AI RMF 1.0, its Generative AI Profile, and a snapshot of the AI RMF Playbook.
This is deliberately version-aware: NIST notes that AI RMF 1.0 is currently being
revised, so the system must preserve the source version and answer date rather than
pretend there is one timeless policy.

## Why this is a strong AI-engineering project

Most RAG demos stop after embedding a PDF and generating a response. EvidenceTrace
is intentionally built around the operational questions an interviewer will ask:

- Can the system retrieve the right evidence, including a specific document version?
- Can it abstain when its corpus does not support the answer?
- Can you measure retrieval quality, trace a request, and catch a regression?
- How do you keep prompts, sources, and generated claims auditable?

## What is implemented

| Concern | Implementation |
| --- | --- |
| Retrieval | SQLite FTS5 lexical retrieval + optional sentence-transformer semantic retrieval, fused with reciprocal-rank fusion |
| Version awareness | Documents store version, source URI, trust tier, source hash, retrieval timestamp, and effective date; search respects `as_of` |
| Grounding | Generated answers are instructed to use retrieved `[S#]` citations; each source includes a PDF page number and response reports citation coverage |
| Safety | Prompt-injection pattern gate; restricted FTS query construction; explicit insufficient-evidence abstention |
| Evaluation | Golden-set retrieval Recall@k and no-answer cases in a reproducible API endpoint |
| Observability | Every query persists a structured trace ID and response payload in SQLite |
| Delivery | FastAPI, AWS Lambda + API Gateway deployment, Docker, health check, GitHub Actions, and tests |

## Architecture

```text
Document ingestion -> versioned SQLite store -> FTS5 + optional semantic retrieval
                                                |             |
                                                +-- RRF fusion +---> cited context
                                                                          |
Question -> guardrail gate -> retrieval -> optional LLM generation -> answer + sources
                                  |                                     |
                                  +------------- structured trace --------+
```

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install ".[dev]"
copy .env.example .env
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs`. It runs without an API key in retrieval-only
mode. To enable semantic reranking, install `pip install ".[semantic]"`, set
`EVIDENCETRACE_SEMANTIC_ENABLED=true`, and run `python scripts/warm_semantic_index.py`.
Embeddings are cached in SQLite by chunk and model name so requests do not recompute
the entire corpus. For LLM answer generation, set `OPENAI_API_KEY` and choose
`OPENAI_MODEL` in `.env`.

Compare lexical retrieval with weighted semantic fusion before enabling it in a
release:

```bash
python scripts/compare_retrieval.py
```

The experiment runner writes a versioned artifact with Recall@k, MRR, page recall,
and abstention for every candidate. Choose the configuration based on that artifact,
not intuition.

The initial empirical decision is documented in [the benchmark note](docs/BENCHMARK.md).

The source-review dashboard is available at `http://localhost:8000/`. It shows
status, supporting PDF pages, citation coverage, latency, and a link to the saved
request trace.

### Load a small synthetic demo corpus locally

Run this command, or use `POST /v1/documents` in the OpenAPI UI:

```bash
python scripts/ingest_file.py data/demo/change_control_policy.md --title "Synthetic Change Control Policy" --source-uri demo://change-control-policy
```

Equivalent API payload:

```json
{
  "title": "Synthetic Change Control Policy",
  "source_uri": "demo://change-control-policy",
  "version": "1.0",
  "trust_tier": "official",
  "content": "A high-risk change affects customer data, an authorization boundary, or a production safety control. It requires an independent reviewer and a rollback plan. Requests outside this policy are escalated to the governance committee."
}
```

Then call `POST /v1/query` with: `When must a reviewer escalate a high-risk change?`

## Evaluation approach

The demo endpoint (`POST /v1/evaluations/demo`) reports retrieval Recall@k. The
repository also contains a NIST-grounded 28-case suite with source and physical-page
labels. Run it after ingestion with:

```bash
python scripts/run_evaluation.py
```

It reports retrieval Recall@k, MRR, page-level citation recall, and abstention rate
and saves the full case-by-case JSON output. Before presenting results, expand it to
75-150 questions reviewed by a subject-matter expert and report:

- Recall@k / MRR for retrieval
- groundedness and citation completeness
- abstention precision on unanswerable questions
- p50/p95 latency, token cost, and failure rate
- regressions between retrieval/prompt/model versions

`scripts/quality_gate.py` enforces the current baseline in CI: Recall@k >= 0.90,
MRR >= 0.80, page recall >= 0.50, and abstention >= 0.75. The baseline is modest on
purpose; raise it only with a versioned evaluation report and do not lower it to
make a failing change appear safe.

## Build the real NIST corpus

```bash
python scripts/build_nist_corpus.py --ingest
```

This downloads the two immutable NIST PDFs listed in the manifest, computes their
SHA-256 values, extracts page-level text, writes a local snapshot, and ingests it.
The raw PDFs and extracted text are git-ignored because they are reproducible source
artifacts rather than authored project code. Run with `--refresh` only when you want
a new source snapshot; do not silently overwrite a prior experiment's corpus.

## Next engineering milestones

1. Expand the labeled evaluation set to 75-150 SME-reviewed questions and publish a
   versioned benchmark report.
2. Add durable trace storage, authentication, rate limiting, and monitoring for a
   multi-user deployment.
3. Benchmark optional semantic retrieval and reranking against the lexical baseline
   before enabling them in production.
