# EvidenceTrace 0.2 implementation plan

Goal: an inspectable AI security and governance evidence workspace, extending the
existing deployed research demo. A release is not a claim of enterprise readiness.

## Release scope

1. Ingest seven primary publications covering governance, operational actions,
   application security, adversarial ML, and secure AI development. Preserve raw
   hashes, extraction snapshots, publication dates, physical pages, and attribution.
2. Expose a live source catalog, source filters, latest/as-of source selection, and
   comparisons between indexed source versions.
3. Add an evidence-review workflow over a submitted text/PDF. Keep internal
   document text out of the public retrieval corpus. Return candidate evidence
   and guidance, explicit uncertainty, and an exportable review with provenance.
4. Gate operator endpoints, bound inputs, validate generated citation syntax, and
   make runtime capabilities explicit. Preserve key-free retrieval/review operation.
5. Provide a usable research/review/library interface and reproducible evaluations.

## Verification

- Hermetic tests for migration, source filtering, temporal selection, provenance,
  review isolation, negative statements, endpoint authorization, and exports.
- Existing 28-case regression suite plus a broader source/page-labeled suite.
- Full extraction and ingest on a separate v0.2 database; benchmark before release.
- Browser smoke test: search, source detail, example review, report export.

## Boundaries

- A candidate passage is not proof that a control is implemented. Automated review
  results require a person to interpret them; no compliance certification is made.
- First release remains a single-operator deployment. SQLite requires a persistent
  volume for durability; Lambda /tmp is not durable storage.
- Cloud rollout, independent expert labels, semantic/reranker experiments, and
  external-provider live tests must be reported separately from completed local work.

## Implemented local release

The seven-source corpus, source catalog, temporal/version filtering, source diffs,
protected review workflow, human decisions and audit events, review comparisons,
Markdown/JSON exports, Gemini/OpenAI adapters, UI, CI gates, and sanitized package
builder are implemented. Semantic RRF was measured locally and remains optional.
See RELEASE_V2.md and BENCHMARK_V2.md for verification and remaining work.
