# Expanded-corpus retrieval benchmark — v0.2

## Method

Seven hash-pinned publications, 497 physical PDF pages, 2,264 chunks. Run
`python scripts/release_report.py` to reproduce the lexical release evaluation.
The report stores source hashes, corpus fingerprint, retrieval version, per-case
source/page results, and local timing. No external LLM is used in these metrics.

Questions are project-authored development/regression cases. Several expansion
questions explicitly name the source and use terms present in section headings;
this makes the expansion suite comparatively easy. It is NOT evidence of perfect
generalization or production answer accuracy. Evaluation cases informed retrieval
iteration; no held-out score is claimed.

## Results

| Corpus / suite | Source hit@5 | MRR | Exact-page hit@5 | Abstention on negatives |
| --- | ---: | ---: | ---: | ---: |
| Original two-document release, 28 NIST cases (historical) | .958 | .852 | .583 | .750 |
| Expanded corpus, same 28 NIST cases | .917 | .844 | .542 | 1.000 |
| Expanded corpus, 21 security-expansion cases | 1.000 | 1.000 | 1.000 | 1.000 |

The API's legacy `retrieval_recall_at_k` field is source hit-rate (at least one
expected source retrieved), not passage-level recall. Page metrics apply only to
cases with physical-page labels. MRR is based on source identity, not whether the
first returned passage answers the question. The two suites contain only four
negative cases each, so 100% abstention should not be generalized.

The exact local latency measurements live in `reports/release-v0.2.json`. They
measure local retrieval without network, LLM generation, load, or Lambda cold
starts; they are not production performance claims.

## Regression analysis

Adding related sources makes retrieval harder. The old two-source suite has a
single expected source for some questions that can now be supported by the Playbook
or other publications. We preserved those labels rather than changing them to
hide misses. Source hit-rate and exact-page hits declined relative to the historical
baseline. Both suites meet the existing minimum release gates (.90 source hit,
.80 MRR, .50 exact-page hit, .75 negative abstention), without lowering thresholds.

Changes with a general retrieval justification:

- Route explicit publication names using reviewed aliases in the corpus catalog.
- Remove matched aliases from content search so publisher names do not overwhelm
  the substantive question.
- Widen lexical candidates before ranking and include multiple sources for broad
  questions; explicit source filters continue to pin the requested scope.
- Penalize table-of-contents dotted leaders and common publication boilerplate.
- Bound long PDF paragraphs while retaining physical-page provenance.

The source routing behavior, empty scopes, version selection, and isolation also
have fixture-based tests independent of the benchmark corpus.

## Semantic experiment

A local sentence-transformer experiment on the expanded NIST suite produced:

| Configuration | Source hit@5 | MRR | Exact-page hit@5 | Negative abstention |
| --- | ---: | ---: | ---: | ---: |
| Lexical release candidate | .917 | .823 | .542 | 1.000 |
| Semantic RRF, weight .25 | .958 | .812 | .500 | 1.000 |
| Semantic RRF, weight .70 | .958 | .837 | .500 | 1.000 |

This exploratory comparison preceded the final dotted-leader and duplicate-overlap fixes.
It is not a held-out comparison; re-run `scripts/compare_retrieval.py` before changing
the default. Semantic retrieval stays optional because the improvement is mixed
and introduces model dependencies, memory, and cold-start costs.

## What is not measured yet

- Independently labeled paraphrases, multi-source synthesis, temporal conflicts,
  and realistic unanswerable questions across a held-out split.
- Claim-level entailment, citation completeness, generated-answer correctness.
- Human-agreed accuracy of design-review findings. Review discovery currently
  proposes lexical candidates and leaves adjudication to a person.
- Concurrent-load behavior, deployed p95 latency, real provider usage/cost,
  extraction fidelity for complex tables/images, and tenant-isolation testing.

Next evaluation work should address these before adding more framework volume.
