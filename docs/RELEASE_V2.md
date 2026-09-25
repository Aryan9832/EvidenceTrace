# EvidenceTrace workspace release v0.2

## Product walkthrough

The product supports a concrete AI design-review task:

1. Find guidance about excessive agency in Research. Inspect the source/page.
2. Open Design reviews and load the illustrative Helpdesk Copilot design.
3. Run all eight review topics. Inspect the internal evidence and primary guidance
   side by side. Note that the sample says prompt-injection testing is *planned*.
4. Record `insufficient_evidence` with the rationale that a plan is not an executed
   test report. The server increments the review revision and appends an event.
5. Export a report. Add a concrete test summary to the design, rerun, and compare
   evidence changes. New evidence does not carry an old human decision forward.
6. Inspect the source catalog, SHA-256 values, and the machine-readable benchmark.

## Design choices

- **Single-operator scope:** explicit authorization and local loopback preview,
  without pretending a shared API key is tenant isolation. Private endpoints and
  provider calls require operator authorization. Local mode rejects cross-origin
  operator requests and is disabled under Lambda.
- **Private input isolation:** uploaded text is processed in memory. Only selected
  excerpts, input fingerprint, and review results are saved. Private text is never
  inserted into public `documents` or `chunks`. Common email/SSN patterns are
  redacted, but this is not a comprehensive DLP system.
- **Human judgment:** topic matching is lexical. Negation/planned-control hints
  encourage close reading, but are not semantic entailment checks. Final statuses
  require a human rationale. The report never supplies a compliance score.
- **Reproducibility:** hash-pinned publications, immutable extraction artifacts,
  corpus fingerprints, source version selection, and report snapshots. `as_of`
  filters publication dates, not legal effective dates or knowledge availability.
- **Review integrity:** optimistic concurrency rejects stale decisions with HTTP
  409; an append-only event table retains each change. This is application-level
  audit history, not cryptographic tamper resistance against a database administrator.
- **Deployment privacy:** packaging exports a fresh public-only database, preserving
  citation IDs but omitting reviews, events, traces, and embeddings. Tests verify
  that the public package has zero private records. Docker excludes local DBs from
  its image and relies on a persistent runtime volume.
- **Cost control:** no provider needed for the core demo. Configured generation is
  operator-only, bounded in output, with a timeout and fallback. Per-process request
  limits are a backstop, not a distributed quota system.

## Verification evidence

- Hermetic unit/API tests cover temporary DB isolation, operator authorization,
  source/version filtering, empty scopes, review non-contamination, negation/plans,
  report exports, review comparisons, stale writes, request limits, and sanitized
  release databases.
- Two versioned retrieval suites with 49 total development/regression questions;
  both release gates run against the actual expanded corpus.
- Browser checks of source counts, search results, exact passage links, the example
  review, and saved reviewer decisions. See the task handoff for executed checks.
- Provider adapters have no live-account validation in this release. An absent
  key is reported in the interface. No customer, user-count, or business-impact
  claims are implied by demo fixtures.

## Deployment status and remaining work

The public AWS URL still runs the earlier release. A local v0.2 workspace and
sanitized Lambda build can be reviewed before any rollout. Private reviews are
explicitly disabled on Lambda because `/tmp` is ephemeral. Full hosted private
reviews require persistent storage and a deployment design appropriate to it.

Before calling this enterprise-ready, complete:

1. Independently reviewed evaluation labels, a held-out split, and claim-level
   grounding evaluation; measure the review workflow with real reviewers.
2. Live provider tests using an account-approved model, recorded token usage, and
   explicit cost budgets. Benchmark a reranker before choosing it.
3. Tenant-aware authentication/authorization, durable managed storage or a backed-up
   single-server volume, retention/deletion operations, and distributed throttling.
4. Background ingestion with job state and retries, OCR/table extraction QA,
   deployment monitoring, concurrency/load tests, and a tested rollback procedure.

This release adds substantial engineering depth, but its candid boundaries are
part of the project. A reviewer can inspect what is implemented and reproduce
the results instead of relying on a list of aspirational technologies.
