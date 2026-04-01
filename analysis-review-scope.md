# Sashiko Review Scope Analysis

## What This Is

An analysis of [Sashiko](https://sashiko.dev/), an LLM-based Linux kernel
patch reviewer, to understand what proportion of its review output addresses
the submitted code changes versus pre-existing issues in surrounding code.

Data was collected via the sashiko.dev public REST API on 2025-04-01.
Classification used pattern matching against review text with ~50 weighted
regex patterns across three categories. The patterns achieve ~93%
classification coverage (7% of findings remain unclassified).

## Background: How Sashiko Reviews Patches

Sashiko does not simply review the diff. Its
[review protocol](https://github.com/masoncl/review-prompts/blob/main/kernel/review-core.md)
explicitly instructs the LLM to gather context beyond the changed lines using
tools (`read_file`, `git_grep`, `find_function`, `find_callchain`,
`find_callers`). The
[design documents](https://github.com/sashiko-dev/sashiko/blob/main/designs/DESIGN_LLM_REVIEW_STRATEGY.md)
state: "If a patch modifies `foo()`, you must read the definition of `foo()`."

The review runs through a
[9-stage pipeline](https://github.com/sashiko-dev/sashiko/blob/main/designs/MULTI_STAGE_REVIEW.md)
(goal analysis, implementation verification, execution flow, resource
management, locking, security, hardware, deduplication, report generation).
Each stage receives the diff plus pre-fetched context including full function
bodies, structs, and callchains.

This context-expansion is by design. The question is: how much of the output
discusses the submitted change versus pre-existing code?

## Methodology

### Data Source

Reviews were fetched from the sashiko.dev API:

- `GET /api/patchsets?per_page=N&page=P&mailing_list=GROUP` — patchset
  listing with finding counts and severity
- `GET /api/review?patchset_id=ID` — full review text with inline commentary

### Content Breakdown

Each review's `inline_review` field contains interleaved quoted diff lines
(prefixed with `>`) and commentary. We separated these mechanically to
measure what proportion of a review is code the author already knows versus
new commentary they need to read.

### Finding Extraction

Individual findings were extracted as commentary blocks between quoted diff
sections. Commit message summaries (text before the first diff quote that
describes what the patch does) were filtered out — they are not findings.

### Finding Classification

Findings were classified using weighted regex pattern matching into three
categories:

1. **Category 1: Patch-specific** — about the actual `+`/`-` lines in the
   diff. Detected by patterns referencing "this patch adds," "the new code,"
   "missing check," "truncation," format string issues, etc.

2. **Category 2: Interaction** — about how new code interacts with existing
   code. Detected by patterns referencing callers/callees, existing
   functions, lock state, concurrent access, error paths, "does this code
   handle," etc. (e.g., "does this new `fput()` cause a double-free because
   the caller already calls `fput()`?")

3. **Category 3: Pre-existing** — about bugs or issues in surrounding code
   that are not introduced by the patch. Detected by explicit language: "not
   introduced by this patch," "pre-existing," "noticed while reviewing,"
   "unrelated to this patch," etc.

Category 3 patterns are the most specific — the LLM often explicitly flags
these. Category 2 patterns are moderately specific (they reference existing
code by name). Category 1 patterns are broader. When a finding matched
multiple categories, the most specific match won: cat3 > cat2 > cat1.

### Duplication Detection

For cross-review duplication, we computed pairwise text similarity
(SequenceMatcher, threshold 0.6) between findings in reviews of different
patches within the same kernel subsystem.

## Results: linux-mm (Exhaustive)

**Coverage:** All 406 patchsets on the linux-mm mailing list as of
2025-04-01. Of the 252 reviews with findings, 204 had cached review data
available for detailed analysis.

### Overview

| Metric | Value |
|---|---|
| Total patchsets on list | 406 |
| Reviewed | 343 (84.5%) |
| Reviews with findings | 252 (73.5% of reviewed) |
| Clean (no findings) | 91 (26.5% of reviewed) |
| Reviews analyzed in detail | 204 of 252 |

**Findings (API-reported across all 252 reviews with findings):** 1,316 total
— 268 low, 346 medium, 562 high, 140 critical. Average 5.2 per review.

### Content Breakdown (Reviews With Findings Only)

What does a patch author actually read when their review has findings?

**Aggregate across 204 reviews:**

| Content Type | Chars | % of Total |
|---|---|---|
| Quoted diff lines | 231,525 | 41.4% |
| Commentary text | 247,752 (35,332 words) | 44.3% |
| Headers/commit summary | 79,428 | 14.2% |

**Per review averages:**

| Metric | Value |
|---|---|
| Total review length | 2,739 chars / 377 words |
| Quoted diff (code author already knows) | 1,135 chars |
| Commentary (what they need to read) | 1,214 chars / 173 words |

**Distributions (p25 / median / p75):**

| Metric | p25 | Median | p75 |
|---|---|---|---|
| Total review length (chars) | 1,947 | 2,578 | 3,320 |
| Total review length (words) | 253 | 350 | 468 |
| Commentary (words) | 109 | 161 | 222 |
| Commentary as % of total | 36% | 43% | 52% |

### Finding Classification

466 individual findings were extracted from the 204 reviews. (The gap vs.
the 1,316 API-reported findings is due to extraction granularity — the API
counts at a finer level than our text-block extraction, and we filter out
commit summaries and snip markers.)

| Category | # | % | Cmnt Chars (avg±σ) | Cmnt Words (avg±σ) | Cmnt Lines (avg±σ) | Full Block Chars (avg±σ) | Full Block Lines (avg±σ) | Quoted Diff (avg chars) | Quote % |
|---|---|---|---|---|---|---|---|---|---|
| Cat 1: Patch-specific | 336 | 72.1% | 522±315 | 74.1±41.9 | 11.2±7.5 | 918±424 | 22.5±10.4 | 396 | 43% |
| Cat 2: Interaction | 54 | 11.6% | 734±337 | 103.1±41.7 | 16.1±8.5 | 1172±511 | 28.3±13.7 | 438 | 35% |
| Cat 3: Pre-existing | 40 | 8.6% | 421±387 | 62.1±52.8 | 9.1±8.8 | 779±530 | 18.5±13.5 | 358 | 49% |
| Unclassified | 36 | 7.7% | 335±165 | 47.2±23.3 | 7.1±3.2 | 683±302 | 16.4±7.1 | 348 | 47% |
| **All findings** | **466** | **100%** | **524±328** | **74.3±43.6** | **11.3±7.8** | **917±450** | **22.4±11.2** | **393** | **43%** |

"Cmnt" columns are commentary only (what the reviewer wrote). "Full Block"
columns include the quoted diff surrounding each finding — what a human
actually sees when reading the email. "Quote %" is how much of the full block
is quoted diff versus commentary.

**Key observations:**

- **~72% of findings are about the submitted patch.** These are the
  core value of the review.
- **~12% are interaction findings** — the bug would only manifest because of
  the new code, but understanding it requires knowledge of existing code. A
  human reviewer would need the same context. These findings are the longest:
  734 chars / 103 words of commentary on average (σ=42), needing more
  words to explain existing code behavior. Their quoted diff ratio is the
  lowest (35%) because the commentary dominates.
- **~9% are pre-existing issues.** The LLM explicitly flags these with
  language like "this isn't a bug introduced by this patch." These have the
  highest standard deviation (σ=53 words) — they range from 12-word typo
  callouts to 254-word descriptions of pre-existing races. Their quoted diff
  ratio is the highest (49%), meaning more of the visual space is code context
  rather than new analysis. About 22% of cat3 findings were classified by the LLM used for this analysis creation as trivial (typos,
  style nits) rather than substantive bugs.  I did not try to make this deterministic as it was a byproduct and not a goal.
- **~8% are unclassified** — LLM review of these shows they are mostly
  cat1/cat2 findings expressed in natural language the patterns don't catch.  However they were left out of further analysis.
- **The average finding occupies ~22 lines in the email** (full block), of
  which about 43% is quoted diff and 57% is commentary. A review with 5
  findings thus occupies roughly 112 lines, consistent with the ~2,739 char
  average review length.

**Reviews containing at least one cat3 finding:** 39 of 204 (19.1%).
So roughly 1 in 5 reviews surfaces something pre-existing.

**Cat3 words as % of all commentary:** ~6.9%.

### What a Patch Author Reads

When a review has findings, the average patch author reads:

```
2,739 chars total
  └─ 1,135 chars quoted diff (code they already know)
  └─ 1,214 chars commentary (173 words), broken down as:
       About their patch:           122 words  (71.9%)
       Patch × existing code:        27 words  (16.1%)
       Pre-existing issues:          12 words   (7.2%)
       Unclassified:                  8 words   (4.9%)
```

However, it may be the case that almost no reviewer receives an "average" review.

### Category 3 Examples (linux-mm)

The 40 cat3 findings range from substantive pre-existing bugs to trivial
nits (as classified by the LLM used for this analytical work):

**Substantive pre-existing bugs:**

- Patchset 5338 (254 words): *"Does this code still leak the context if the
  subsequent call to `damon_call()` fails?"* — describes a pre-existing leak
  path in kdamond thread startup.
- Patchset 5055 (159 words): *"Could exposing `MADV_COLLAPSE` to automated
  continuous execution via DAMOS trigger a pre-existing use-after-free in the
  core madvise logic?"*
- Patchset 5367 (128 words): *"This isn't a bug introduced by this patch,
  but while reviewing `sparse_init_nid()`, I noticed a potential regression
  with how `sparse_usagebuf` slots are consumed."*

**Trivial nits (still flagged as pre-existing):**

- Patchset 2227 (14 words): *"This isn't a bug, but there is a typo
  (increaed) in the comment above."*
- Patchset 2493 (13 words): *"This isn't a bug, but there's a typo
  (selftets) in the subject line."*
- Patchset 4586 (12 words): *"This isn't a bug, but there is a typo here
  (parametr)."*

### Cat3 Impact on Affected Reviews

The aggregate numbers (9% of findings, 7% of commentary) understate the
impact on the reviews that actually contain cat3 findings. Because cat3
findings cluster — they either appear or they don't — the experience
differs sharply between the 80% of reviews without cat3 and the 20% with.

**39 of 204 reviews (19.1%) contain at least one cat3 finding.** In those
39 reviews:

| Metric | With cat3 | Without cat3 | Difference |
|---|---|---|---|
| Avg review length (lines) | 78 | 59 | +19 lines |
| Cat3 lines per review (avg±σ) | 19±15 | — | — |
| Cat3 as % of review (avg±σ) | 28%±22% | — | — |
| Cat3 findings per review (avg±σ) | 1.0±0.2 | — | — |

Almost every affected review has exactly one cat3 finding. That single
finding adds an average of 19 lines — expanding a review that would
otherwise be ~59 lines to ~78 lines. For roughly 1 in 5 patch authors,
28% of what they read concerns an issue they did not introduce.

The range is wide. At the low end, trivial cat3 findings (typo callouts)
add a few lines. At the high end, several reviews are majority cat3:

| Patchset | Review lines | Cat3 lines | Cat3 % |
|---|---|---|---|
| 3503 | 100 | 75 | 75% |
| 5338 | 67 | 55 | 82% |
| 4649 | 65 | 53 | 82% |
| 639 | 44 | 28 | 64% |
| 5055 | 51 | 31 | 61% |

**What this means for the patch author:** When you submit a patch to a
subsystem like linux-mm and get an AI review, there is roughly a 1-in-5
chance that ~19 lines of that review will describe a pre-existing issue —
a bug, race, leak, or typo — that exists in the code you're modifying but
that you did not create. You are now the person who has been told about
it. Whether you feel responsible for fixing it is a social question, not
a technical one, but the review has put it in your inbox.

## Results: LKML (linux-kernel)

**Sample:** 500 of 4,765 total patchsets (10.5% of all patchsets on LKML as
of 2025-04-01). Of those 500, 200 reviews with findings were analyzed in
detail using the earlier (less refined) classification method.

| Metric | Value |
|---|---|
| Patchsets reviewed | 487 of 500 (97.4%) |
| Reviews with findings | 265 of 487 (54.4%) |
| Reviews with no findings | 222 of 487 (45.6%) |
| Total findings (200 analyzed reviews) | 981 |
| Average findings per review (with findings) | 4.9 |
| Average review length (with findings) | ~1,949 chars |

**Severity breakdown (200 analyzed reviews):** 164 low, 243 medium, 518
high, 56 critical.

**Category 3 (pre-existing) classification:** 9.5% of reviews contained
explicit pre-existing language (19 of 200). This is broadly consistent with
the linux-mm exhaustive result of 8.9% of findings being cat3.

### Notable Difference: Findings Rate

LKML shows a significantly lower findings rate (54.4%) compared to linux-mm
(73.5%). This likely reflects the broader diversity of LKML subsystems —
linux-mm concentrates on memory management code, which has dense
interdependencies that generate more findings.

## Results: Cross-Review Duplication

**Finding: Effectively zero duplication was detected.**

Across 16 subsystems with 5+ reviewed patches each on LKML, only 1 pair of
findings exceeded the 0.6 similarity threshold. That pair was from the same
author (Ian Rogers) submitting similar perf architecture patches — the
similarity reflected similar code being changed, not the same pre-existing
bug surfacing repeatedly.

## Interpretation

### Most Review Content Is About the Submitted Patch (~85%)

Combining categories 1 and 2, roughly 84% of finding text (by word count) is
about the submitted change or its direct interaction with existing code.
Category 2 (interaction) findings are arguably the most valuable type a
reviewer can produce — they require deep understanding of the surrounding
codebase to identify.

### Pre-existing Findings Are Modest in Aggregate but Significant per Review

About 9% of findings explicitly discuss pre-existing issues. Averaged
across all reviews, they represent about 6.9% of the commentary — roughly
12 words per review.

But this average conceals a bimodal distribution. 81% of reviews contain
zero cat3 findings. The other 19% contain cat3 findings that constitute
28% of the review on average, adding ~19 lines to what the patch author
must read. In those reviews, the author receives a ~78-line email where
only ~59 lines concern their actual submission. Several reviews are
majority cat3 — the patch author opens an email that is overwhelmingly
about problems they did not create.

Many cat3 findings, as determined by the LLM used for this analysis creation, are trivial (typos, style nits) rather than deep bugs.
The substantive pre-existing bugs — races, use-after-frees, leaks in
existing code paths — are a smaller subset.

### Cross-Review Duplication Is Not a Problem; Per-Review Burden Is

The hypothesis that pre-existing bugs would surface repeatedly as "review
bloat" — the same problems appearing in every review touching the same
subsystem — is **not supported** by this data. Cross-review duplication was
essentially zero.

However, the per-review burden on affected authors is real. When cat3
appears, it doesn't repeat across reviews — it inflates that specific
review by ~32%. The concern is not aggregate bloat across a mailing list
but localized burden on individual contributors who happen to touch code
with pre-existing issues.

The lack of cross-review duplication may be because:

1. Sashiko's stage 8 (verification/deduplication) is effective at filtering
2. The LLM's non-deterministic nature means it focuses on different aspects
   each time
3. The review prompt's
   [inline template](https://github.com/masoncl/review-prompts/blob/main/kernel/inline-template.md)
   aggressively snips output, so even if the LLM noticed the same issues, they
   may not survive into the final review

### Interaction Findings Are the Longest

Category 2 findings average 103 words — 39% longer than patch-specific
findings (74 words). This is expected: explaining how new code interacts
badly with existing code requires describing the existing behavior. This is
also exactly what makes them valuable to a human reviewer who may not have
that context memorized.

## API Reference

For anyone wanting to reproduce or extend this analysis:

```
Base URL: https://sashiko.dev/api/

GET /api/lists
  Returns all monitored mailing lists with group IDs.

GET /api/patchsets?per_page=N&page=P&mailing_list=GROUP
  Paginated patchset listing. Each patchset includes findings_low,
  findings_medium, findings_high, findings_critical counts.

GET /api/review?patchset_id=ID
  Full review including inline_review text, stage logs with LLM
  chain-of-thought, and baseline info.

GET /api/stats
GET /api/stats/timeline
GET /api/stats/reviews
  Aggregate statistics.
```

## Caveats

- This is a point-in-time snapshot (2025-04-01). The mailing lists are
  actively growing.
- The linux-mm analysis covers the full list (406 patchsets, 204 analyzed in
  detail). The LKML analysis covers 500 of 4,765 patchsets (10.5%).
- Classification uses regex pattern matching, not semantic understanding.
  7.2% of findings remained unclassified; LLM review suggests these are
  mostly cat1/cat2. The patterns likely misclassify some borderline findings
  between categories, but the overall proportions are directionally sound.
- The duplication analysis uses simple text similarity. Semantically similar
  findings expressed in different words would not be detected.
- We did not have access to the actual diff content via the API, which
  would have enabled more precise line-level comparison of finding targets
  versus changed lines.
- 48 of 252 reviews with findings on linux-mm returned 404 from the API and
  could not be analyzed. If these differ systematically from the 204 that
  were analyzed, the proportions could shift.
