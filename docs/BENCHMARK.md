# Retrieval benchmark: NIST corpus v0.1

## Scope

The first evaluation uses 28 human-authored questions over two primary NIST PDFs:

- NIST AI 100-1, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*
- NIST AI 600-1, *Artificial Intelligence Risk Management Framework: Generative AI Profile*

Each answerable test case has an expected source and physical PDF page. Four cases
are intentionally unanswerable or unsafe. The test suite is a regression baseline,
not a claim of general benchmark performance.

## Results

| Configuration | Recall@5 | MRR | Exact-page recall@5 | Abstention |
| --- | ---: | ---: | ---: | ---: |
| Lexical FTS5 + title routing + page diversity | 0.958 | 0.852 | 0.583 | 0.750 |
| + semantic RRF, weight 0.25 | 0.917 | 0.875 | 0.625 | 0.750 |
| + semantic RRF, weight 1.00 | 0.917 | 0.868 | 0.667 | 0.750 |

## Decision

Lexical retrieval remains the default because it has the highest source Recall@5.
Semantic fusion remains an optional, measured experiment: it improves MRR and
page-level recall but currently loses one source-level hit. It will not become the
default until a larger held-out suite shows that this trade-off is acceptable.

## Next experiment

1. Expand to 75-150 independently reviewed questions.
2. Split evaluation data into development and held-out sets before tuning.
3. Compare a cross-encoder reranker only on the top lexical/semantic candidate set.
4. Measure latency and cost alongside retrieval quality.

The generated machine-readable experiment outputs are deliberately git-ignored and
must be regenerated with `python scripts/compare_retrieval.py` for each corpus or
retrieval-version change.
