# Sashiko Review Scope Analysis

[Sashiko](https://sashiko.dev/) is an LLM-based Linux kernel patch reviewer.
Daroc Alden wrote [an article about it in LWN](https://lwn.net/Articles/1064830/)
that prompted a question nobody had numbers for: how much of Sashiko's output
is about the submitted change versus pre-existing issues in surrounding code?

This repository contains a data analysis that answers that question. It was
built to accompany a [blog post I wrote](https://www.bexelbie.com/2026/04/01/whats-in-a-sashiko-review).

## Headline findings (linux-mm mailing list)

- ~72% of findings are patch-specific
- ~12% are about how new code interacts with existing code
- ~9% are about pre-existing issues the patch didn't introduce

- That 9% is unevenly distributed: ~20% of reviews contain pre-existing
  findings, and in those reviews they add ~19 lines (~28% of the review)

- A second hypthoesis about cross-review duplication was disproven
  as it is effectively zero — it's not the same bugs surfacing repeatedly

## How it was built

All code in this repository was written by an LLM (Claude). Classification
uses deterministic regex pattern matching (~50 weighted patterns), not LLM
judgment. The analysis document was drafted by an LLM and edited by a human
for accuracy and precision; the human did not edit for word choice or structure.

## Files

### Analysis

- **[analysis-review-scope.md](analysis-review-scope.md)** — Full data
  analysis with methodology, tables, and interpretation. LLM-drafted,
  human-edited for accuracy and precision.

### Code

All code was written by an LLM.

- **[classify_findings.py](classify_findings.py)** — Deterministic classifier
  and statistics engine. Extracts findings from cached reviews, classifies
  them into three categories using regex pattern matching, and produces all
  statistics tables. This is the core reproducibility artifact.
- **[fetch_cache.py](fetch_cache.py)** — Downloads patchset metadata and
  reviews from the sashiko.dev public API into `cache/`. Run this first to
  populate the cache before running the classifier.

### Data

- **[output.txt](output.txt)** — Raw output from the most recent
  `classify_findings.py` run. All numbers in the analysis document are
  derived from this output.
- **cache/** — Downloaded API data. Contains `patchsets.json` (406 patchset
  metadata records) and 345 individual `review_*.json` files fetched from
  sashiko.dev on 2025-04-01. Also contains `analysis_results.json`, an
  intermediate summary produced by the classifier. The cache exists to avoid
  repeatedly hitting the sashiko.dev API; re-running `fetch_cache.py` will
  regenerate it.

## Reproducing the analysis

```
python3 fetch_cache.py    # download reviews (or use existing cache/)
python3 classify_findings.py
```

The classifier reads from `cache/` and prints results to stdout. Pipe to a
file to capture: `python3 classify_findings.py > output.txt`

## License

Code and analysis are released under [0BSD](LICENSE). The cached API data
in `cache/` is not covered by this license — see LICENSE for details.
