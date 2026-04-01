# ABOUTME: Classifies findings from cached Sashiko reviews into three categories using
# ABOUTME: weighted regex pattern matching, and computes per-category size statistics.

import json
import os
import re
import sys
from collections import defaultdict

DEFAULT_CACHE_DIR = "cache"

# --- Classification patterns ---
# Each tuple: (pattern, weight). Higher weight = stronger signal.
# Cat3 patterns are most specific (explicit "not introduced by this patch" language).
# Cat2 patterns reference callers/callees, existing code, lock state, concurrent access.
# Cat1 patterns are broadest (questions about "this" code, format strings, etc.).
# When a finding matches multiple categories, the most specific match wins: cat3 > cat2 > cat1.

CAT3_PATTERNS = [
    (r"not\s+(a\s+bug\s+)?introduced\s+by\s+this\s+(patch|commit|change)", 10),
    (r"pre-?existing", 10),
    (r"noticed\s+while\s+reviewing", 8),
    (r"unrelated\s+to\s+this\s+(patch|commit|change)", 10),
    (r"this\s+isn't\s+a\s+bug\s+(introduced|caused)", 10),
    (r"this\s+isn't\s+a\s+bug,\s+but", 8),
    (r"existing\s+(bug|issue|problem|race|leak)", 6),
    (r"already\s+(present|exists|existed)\s+(before|prior|in\s+the\s+current)", 8),
    (r"not\s+(caused|created)\s+by\s+this", 8),
    (r"separate\s+(issue|bug|problem|patch)", 5),
    (r"outside\s+(the\s+scope\s+of|of)\s+this\s+(patch|change)", 8),
    (r"pre-?dates\s+this", 8),
    (r"regardless\s+of\s+this\s+(patch|change)", 6),
]

CAT2_PATTERNS = [
    (r"caller[s]?\s+(of|already|also|will|might|may|does|do)", 5),
    (r"callee[s]?\s+(of|already|also|will|might|may)", 5),
    (r"(does|will|could|might|can)\s+the\s+(existing|current|caller|callee)", 4),
    (r"existing\s+(code|function|implementation|caller|path)", 4),
    (r"(concurrent|simultaneous|parallel)\s+(access|call|execution|thread)", 5),
    (r"lock\s+(ordering|hierarchy|contention|held|state)", 4),
    (r"(held|holding)\s+(the|a|this)\s+(lock|mutex|spinlock|semaphore)", 4),
    (r"(double|duplicate)\s+(free|close|release|put|drop)", 5),
    (r"use.after.free", 5),
    (r"(reference|ref)\s+(count|counting|leak|imbalance)", 4),
    (r"(other|another)\s+(thread|process|cpu|context)\s+(might|could|may|will)", 4),
    (r"(current|existing)\s+(implementation|behavior|logic|code)\s+(does|doesn't|already)", 3),
    (r"interact(s|ion)?\s+with\s+(existing|current|the)", 3),
    (r"(races?|racy)\s+with", 4),
    (r"(abba|deadlock|livelock)\s+(between|with|if|when)", 5),
    (r"(what|how)\s+(happens|does|would)\s+(if|when)\s+(the|a|another)", 3),
    (r"error\s+path\s+(in|of|from)\s+(the|a)\s+(caller|existing|current)", 4),
]

CAT1_PATTERNS = [
    (r"this\s+(patch|commit|change)\s+(adds?|removes?|introduces?|modifies?|changes?)", 3),
    (r"(the\s+)?new\s+(code|function|check|logic|implementation|helper|macro)", 3),
    (r"(missing|lacks?|needs?|should\s+have)\s+(a\s+)?(check|validation|error\s+handling|null\s+check)", 4),
    (r"(format|printf)\s+(string|specifier)", 3),
    (r"(truncat|overflow|underflow|wrap)", 3),
    (r"(return|error)\s+(value|code|status)\s+(is\s+)?(not\s+)?(checked|handled|ignored|propagated)", 3),
    (r"(uninitiali[sz]ed|uninitialized)\s+(variable|value|field|pointer|memory)", 4),
    (r"(memory|resource)\s+(leak|not\s+freed|not\s+released)", 3),
    (r"(should|could|might|may)\s+(this|the\s+new|the\s+added)", 2),
    (r"(off.by.one|fencepost|boundary)", 3),
    (r"(integer|arithmetic)\s+(overflow|underflow|truncation|wrap)", 3),
    (r"(this|the)\s+(addition|removal|change|modification|patch|code)", 2),
    (r"(question|concern|suggestion|nit).*(:|\?)", 2),
    (r"(the\s+)?(patch|diff|change)\s+(itself|here|above|below)", 2),
    (r"(this|the)\s+(new|added|introduced|modified|changed)\s+(code|line|function|block)", 3),
    (r"(bug|issue|problem|error|mistake)\s+(in|with)\s+(this|the\s+new|the\s+added)", 4),
    (r"(shouldn't|should\s+not|must\s+not|cannot|can't)\s+this", 2),
    # Broad question patterns about the code being reviewed
    (r"(will|does|could|would|can|is|are|should)\s+(this|the)\s+\w+", 2),
    (r"(similarly|also),?\s+(could|should|does|will|is)", 2),
    (r"\?\s*$", 1),  # Ends with a question mark — likely asking about the code
    (r"(instead\s+of|rather\s+than|replace|use\s+.*\s+instead)", 2),
    (r"(silently|accidentally|inadvertently|unexpectedly)", 2),
    (r"(compilation|compile|build)\s+(error|failure|warning)", 3),
    (r"(storing|store)\s+.*\s+(truncat|overflow|lose|lost)", 3),
    (r"(redundant|unnecessary|unneeded|dead\s+code)", 2),
    (r"(typo|misspell|spell)", 2),
    (r"(accurate|correct)\s+(description|comment|documentation)", 2),
    (r"(printed|print|format)\s+with\s+%", 2),
    (r"(match|matches)\s+(its|the|unsigned|signed)", 2),
    (r"(simplif|simpli[sz]e)", 2),
    (r"(is\s+this|are\s+these)\s+(description|comment|check|needed|correct|accurate|safe)", 2),
]


def classify_finding(text):
    """Classify a finding block. Returns (category, score)."""
    text_lower = text.lower()

    cat3_score = sum(w for p, w in CAT3_PATTERNS if re.search(p, text_lower))
    cat2_score = sum(w for p, w in CAT2_PATTERNS if re.search(p, text_lower))
    cat1_score = sum(w for p, w in CAT1_PATTERNS if re.search(p, text_lower))

    # Cat3 trumps if any match at all (most specific)
    if cat3_score > 0:
        return "cat3_preexisting", cat3_score
    # Cat2 wins if it matches at all alongside cat1 (more specific than cat1)
    if cat2_score > 0:
        return "cat2_interaction", cat2_score
    if cat1_score > 0:
        return "cat1_patch", cat1_score
    return "unclassified", 0


def is_commit_summary(text):
    """Detect commit message summaries that should not be classified as findings."""
    lines = text.strip().split("\n")
    if not lines:
        return False
    first = lines[0].strip().lower()
    # Summaries typically start with "This commit/patch [verb]s..." without questions
    summary_starts = [
        r"^this\s+(commit|patch|change|series|set)\s+(adds?|removes?|introduces?|modifies?|changes?|cleans?|refactors?|fixes?|updates?|converts?|replaces?|moves?|renames?|splits?|merges?)",
        r"^the\s+(commit|patch|change|series)\s+(adds?|removes?|introduces?|modifies?|changes?|cleans?|refactors?|fixes?|updates?)",
    ]
    if any(re.search(p, first) for p in summary_starts):
        # Only filter if there's no question mark (actual findings ask questions)
        if "?" not in text:
            return True
    return False


def extract_findings(inline_review):
    """Extract individual findings from an inline review.

    A finding is a commentary block between quoted diff sections.
    Returns list of dicts with text, line counts, and surrounding context.
    """
    if not inline_review:
        return []

    lines = inline_review.split("\n")
    findings = []
    current_commentary = []
    current_quoted = []
    in_header = True

    for line in lines:
        # Skip header lines (Author:, Subject:, commit hash)
        if in_header:
            if line.startswith(">"):
                in_header = False
            elif line.startswith("Author:") or line.startswith("Subject:"):
                continue
            elif re.match(r"^[0-9a-f]{40}", line):
                continue
            else:
                # Pre-diff commentary (commit summary)
                continue

        if line.startswith(">"):
            # Quoted diff line
            if current_commentary:
                text = "\n".join(current_commentary).strip()
                if _is_real_finding(text):
                    findings.append({
                        "commentary": text,
                        "preceding_quoted": list(current_quoted),
                    })
                current_commentary = []
                current_quoted = []
            current_quoted.append(line)
        else:
            current_commentary.append(line)

    # Trailing commentary
    if current_commentary:
        text = "\n".join(current_commentary).strip()
        if _is_real_finding(text):
            findings.append({
                "commentary": text,
                "preceding_quoted": list(current_quoted),
            })

    return findings


def _is_real_finding(text):
    """Filter out non-finding blocks: snip markers, blank lines, summaries, etc."""
    if not text:
        return False
    # Filter snip markers like "[ ... ]"
    stripped = text.strip()
    if re.match(r"^\[?\s*\.\.\.\s*\]?$", stripped):
        return False
    # Filter very short blocks (< 5 words) unless they contain a clear signal
    words = len(stripped.split())
    if words < 5:
        return False
    # Filter embedded diff headers that leaked into commentary
    if stripped.startswith("diff --git") or stripped.startswith("---"):
        return False
    # Filter commit summaries
    if is_commit_summary(stripped):
        return False
    return True


def compute_stats(values):
    """Compute mean and std dev for a list of numbers."""
    if not values:
        return 0, 0
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, 0
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return mean, variance ** 0.5


def compute_percentiles(values, percentiles=(25, 50, 75)):
    """Compute percentiles for a list of numbers."""
    if not values:
        return {p: 0 for p in percentiles}
    s = sorted(values)
    n = len(s)
    result = {}
    for p in percentiles:
        k = (n - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < n else f
        result[p] = s[f] + (k - f) * (s[c] - s[f])
    return result


def analyze_cache(cache_dir):
    """Run full classification analysis on cached review data."""
    # Load patchset index
    with open(os.path.join(cache_dir, "patchsets.json")) as f:
        patchset_data = json.load(f)

    patchsets = patchset_data["items"]
    total = patchset_data["total"]

    # Load all available reviews
    reviews = {}
    for ps in patchsets:
        path = os.path.join(cache_dir, f"review_{ps['id']}.json")
        if os.path.exists(path):
            with open(path) as f:
                review = json.load(f)
            if review.get("inline_review") and len(review["inline_review"]) > 50:
                reviews[ps["id"]] = review

    # Compute overview stats from patchset metadata
    reviewed_count = sum(1 for ps in patchsets if ps.get("status") == "Reviewed")
    with_findings = sum(
        1 for ps in patchsets
        if ps.get("status") == "Reviewed"
        and sum(ps.get(f"findings_{s}", 0) for s in ["low", "medium", "high", "critical"]) > 0
    )
    api_findings = {
        s: sum(ps.get(f"findings_{s}", 0) for ps in patchsets)
        for s in ["low", "medium", "high", "critical"]
    }
    api_total_findings = sum(api_findings.values())

    print(f"Total patchsets: {total}")
    if total > 0:
        print(f"Reviewed: {reviewed_count} ({100*reviewed_count/total:.1f}%)")
    else:
        print(f"Reviewed: {reviewed_count}")
    if reviewed_count > 0:
        print(f"With findings: {with_findings} ({100*with_findings/reviewed_count:.1f}% of reviewed)")
        print(f"Clean (no findings): {reviewed_count - with_findings} ({100*(reviewed_count - with_findings)/reviewed_count:.1f}% of reviewed)")
    else:
        print(f"With findings: {with_findings}")
        print(f"Clean (no findings): {reviewed_count - with_findings}")
    print(f"Reviews analyzed in detail: {len(reviews)} of {with_findings}")
    print(f"\nAPI-reported findings: {api_total_findings} total "
          f"-- {api_findings['low']} low, {api_findings['medium']} medium, "
          f"{api_findings['high']} high, {api_findings['critical']} critical")
    if with_findings > 0:
        print(f"Average findings per review (API): {api_total_findings/with_findings:.1f}")

    # Content breakdown
    total_quoted_chars = 0
    total_commentary_chars = 0
    total_commentary_words = 0
    total_header_chars = 0

    # Per-review collectors for distributions
    review_total_chars_list = []
    review_total_words_list = []
    review_commentary_chars_list = []
    review_commentary_words_list = []
    review_commentary_pct_list = []

    # Classification
    category_findings = defaultdict(list)
    per_review_data = []

    for ps_id, review in reviews.items():
        text = review["inline_review"]
        lines = text.split("\n")

        # Content breakdown for this review
        quoted_chars = 0
        commentary_chars = 0
        header_chars = 0
        in_hdr = True

        for line in lines:
            if line.startswith(">"):
                quoted_chars += len(line) + 1
                in_hdr = False
            elif in_hdr:
                header_chars += len(line) + 1
            else:
                commentary_chars += len(line) + 1

        total_quoted_chars += quoted_chars
        total_commentary_chars += commentary_chars
        total_header_chars += header_chars
        header_words = 0
        hdr_check = True
        for l in lines:
            if l.startswith(">"):
                hdr_check = False
            elif hdr_check:
                header_words += len(l.split())
        commentary_words = len(text.split()) - sum(
            len(l.split()) for l in lines if l.startswith(">")
        ) - header_words
        total_commentary_words += commentary_words

        total_review_words = len(text.split())
        total_review_chars = len(text)

        review_total_chars_list.append(total_review_chars)
        review_total_words_list.append(total_review_words)
        review_commentary_chars_list.append(commentary_chars)
        review_commentary_words_list.append(commentary_words)
        if total_review_chars > 0:
            review_commentary_pct_list.append(100 * commentary_chars / total_review_chars)

        # Extract and classify findings
        findings = extract_findings(text)
        review_cats = defaultdict(list)

        for finding in findings:
            cat, score = classify_finding(finding["commentary"])
            cmnt = finding["commentary"]
            cmnt_chars = len(cmnt)
            cmnt_words = len(cmnt.split())
            cmnt_lines = cmnt.count("\n") + 1

            # Full block: commentary + preceding quoted diff
            quoted_text = "\n".join(finding["preceding_quoted"])
            full_block = quoted_text + "\n" + cmnt if quoted_text else cmnt
            full_chars = len(full_block)
            full_lines = full_block.count("\n") + 1
            quote_chars = len(quoted_text)

            entry = {
                "category": cat,
                "score": score,
                "cmnt_chars": cmnt_chars,
                "cmnt_words": cmnt_words,
                "cmnt_lines": cmnt_lines,
                "full_chars": full_chars,
                "full_lines": full_lines,
                "quote_chars": quote_chars,
                "quote_pct": quote_chars / full_chars if full_chars > 0 else 0,
                "text": cmnt[:200],
            }
            category_findings[cat].append(entry)
            review_cats[cat].append(entry)

        per_review_data.append({
            "patchset_id": ps_id,
            "total_chars": len(text),
            "total_lines": len(lines),
            "quoted_chars": quoted_chars,
            "commentary_chars": commentary_chars,
            "commentary_words": commentary_words,
            "findings": len(findings),
            "categories": {k: len(v) for k, v in review_cats.items()},
            "cat3_full_lines": sum(f["full_lines"] for f in review_cats.get("cat3_preexisting", [])),
            "total_full_lines": sum(
                f["full_lines"] for cat_list in review_cats.values() for f in cat_list
            ),
        })

    # Print results
    print(f"\n{'='*80}")
    print(f"CONTENT BREAKDOWN ({len(reviews)} reviews with findings)")
    print(f"{'='*80}")
    total_all = total_quoted_chars + total_commentary_chars + total_header_chars
    n = len(reviews)
    if n == 0 or total_all == 0:
        print("  No reviews to analyze.")
        return
    print(f"Quoted diff:  {total_quoted_chars:>10,} chars ({100*total_quoted_chars/total_all:.1f}%)")
    print(f"Commentary:   {total_commentary_chars:>10,} chars ({100*total_commentary_chars/total_all:.1f}%) = {total_commentary_words:,} words")
    print(f"Headers:      {total_header_chars:>10,} chars ({100*total_header_chars/total_all:.1f}%)")

    print(f"\nPer-review averages:")
    print(f"  Total:      {total_all/n:,.0f} chars / {sum(review_total_words_list)/n:.0f} words (incl quoted diff)")
    print(f"  Quoted:     {total_quoted_chars/n:,.0f} chars")
    print(f"  Commentary: {total_commentary_chars/n:,.0f} chars / {total_commentary_words/n:,.0f} words")

    print(f"\nPer-review distributions (p25 / median / p75):")
    tc_pct = compute_percentiles(review_total_chars_list)
    tw_pct = compute_percentiles(review_total_words_list)
    cw_pct = compute_percentiles(review_commentary_words_list)
    cp_pct = compute_percentiles(review_commentary_pct_list)
    print(f"  Total chars:        {tc_pct[25]:,.0f} / {tc_pct[50]:,.0f} / {tc_pct[75]:,.0f}")
    print(f"  Total words:        {tw_pct[25]:.0f} / {tw_pct[50]:.0f} / {tw_pct[75]:.0f}")
    print(f"  Commentary words:   {cw_pct[25]:.0f} / {cw_pct[50]:.0f} / {cw_pct[75]:.0f}")
    print(f"  Commentary as % of total: {cp_pct[25]:.0f}% / {cp_pct[50]:.0f}% / {cp_pct[75]:.0f}%")

    print(f"\n{'='*80}")
    print(f"FINDING CLASSIFICATION")
    print(f"{'='*80}")
    total_findings = sum(len(v) for v in category_findings.values())
    print(f"Total findings extracted: {total_findings}")

    for cat in ["cat1_patch", "cat2_interaction", "cat3_preexisting", "unclassified"]:
        entries = category_findings[cat]
        if not entries:
            continue
        pct = 100 * len(entries) / total_findings
        cc_avg, cc_std = compute_stats([e["cmnt_chars"] for e in entries])
        cw_avg, cw_std = compute_stats([e["cmnt_words"] for e in entries])
        cl_avg, cl_std = compute_stats([e["cmnt_lines"] for e in entries])
        fc_avg, fc_std = compute_stats([e["full_chars"] for e in entries])
        fl_avg, fl_std = compute_stats([e["full_lines"] for e in entries])
        qp_avg = sum(e["quote_pct"] for e in entries) / len(entries)

        print(f"\n  {cat}: {len(entries)} ({pct:.1f}%)")
        print(f"    Commentary: {cc_avg:.0f}±{cc_std:.0f} chars, {cw_avg:.1f}±{cw_std:.1f} words, {cl_avg:.1f}±{cl_std:.1f} lines")
        print(f"    Full block: {fc_avg:.0f}±{fc_std:.0f} chars, {fl_avg:.1f}±{fl_std:.1f} lines, {100*qp_avg:.0f}% quoted")

    # All findings aggregate
    all_entries = [e for v in category_findings.values() for e in v]
    if all_entries:
        cc_avg, cc_std = compute_stats([e["cmnt_chars"] for e in all_entries])
        cw_avg, cw_std = compute_stats([e["cmnt_words"] for e in all_entries])
        cl_avg, cl_std = compute_stats([e["cmnt_lines"] for e in all_entries])
        fc_avg, fc_std = compute_stats([e["full_chars"] for e in all_entries])
        fl_avg, fl_std = compute_stats([e["full_lines"] for e in all_entries])
        qp_avg = sum(e["quote_pct"] for e in all_entries) / len(all_entries)
        qc_avg = sum(e["quote_chars"] for e in all_entries) / len(all_entries)
        print(f"\n  ALL: {len(all_entries)} (100%)")
        print(f"    Commentary: {cc_avg:.0f}±{cc_std:.0f} chars, {cw_avg:.1f}±{cw_std:.1f} words, {cl_avg:.1f}±{cl_std:.1f} lines")
        print(f"    Full block: {fc_avg:.0f}±{fc_std:.0f} chars, {fl_avg:.1f}±{fl_std:.1f} lines, {100*qp_avg:.0f}% quoted")
        print(f"    Quoted diff avg: {qc_avg:.0f} chars")

    # Cat3 per-review impact
    print(f"\n{'='*80}")
    print(f"CAT3 PER-REVIEW IMPACT")
    print(f"{'='*80}")
    cat3_reviews = [r for r in per_review_data if r["categories"].get("cat3_preexisting", 0) > 0]
    print(f"Reviews with cat3: {len(cat3_reviews)} of {len(per_review_data)} ({100*len(cat3_reviews)/len(per_review_data):.1f}%)")

    if cat3_reviews:
        with_lines = [r["total_lines"] for r in cat3_reviews]
        without_lines = [r["total_lines"] - r["cat3_full_lines"] for r in cat3_reviews]
        cat3_lines = [r["cat3_full_lines"] for r in cat3_reviews]
        cat3_pct = [100 * r["cat3_full_lines"] / r["total_lines"]
                     for r in cat3_reviews if r["total_lines"] > 0]
        cat3_per_review_count = [r["categories"].get("cat3_preexisting", 0) for r in cat3_reviews]

        w_avg, w_std = compute_stats(with_lines)
        wo_avg, wo_std = compute_stats(without_lines)
        c3_avg, c3_std = compute_stats(cat3_lines)
        cp_avg, cp_std = compute_stats(cat3_pct)
        cn_avg, cn_std = compute_stats(cat3_per_review_count)

        print(f"  Review lines (with cat3):    {w_avg:.0f}±{w_std:.0f}")
        print(f"  Review lines (without cat3): {wo_avg:.0f}±{wo_std:.0f}")
        print(f"  Cat3 adds:                   {c3_avg:.0f}±{c3_std:.0f} lines")
        print(f"  Cat3 as % of review:         {cp_avg:.0f}±{cp_std:.0f}%")
        print(f"  Cat3 findings per review:    {cn_avg:.1f}±{cn_std:.1f}")

        # Top cat3 reviews by cat3 percentage of total review
        cat3_detail = sorted(
            [(r["patchset_id"], r["total_lines"], r["cat3_full_lines"],
              100 * r["cat3_full_lines"] / r["total_lines"] if r["total_lines"] > 0 else 0)
             for r in cat3_reviews],
            key=lambda x: x[3], reverse=True
        )
        print(f"\n  Top cat3 reviews (by cat3 % of total review lines):")
        print(f"  {'Patchset':>10}  {'Review lines':>12}  {'Cat3 lines':>10}  {'Cat3 %':>7}")
        for ps_id, total_l, cat3_l, cat3_p in cat3_detail[:10]:
            print(f"  {ps_id:>10}  {total_l:>12}  {cat3_l:>10}  {cat3_p:>6.0f}%")

    # Per-category word breakdown (what fraction of commentary words per review)
    print(f"\n{'='*80}")
    print(f"PER-REVIEW WORD BREAKDOWN BY CATEGORY")
    print(f"{'='*80}")
    total_cat_words = {}
    for cat in ["cat1_patch", "cat2_interaction", "cat3_preexisting", "unclassified"]:
        total_cat_words[cat] = sum(e["cmnt_words"] for e in category_findings[cat])
    all_cat_words = sum(total_cat_words.values())
    if all_cat_words > 0 and n > 0:
        for cat in ["cat1_patch", "cat2_interaction", "cat3_preexisting", "unclassified"]:
            per_review = total_cat_words[cat] / n
            pct = 100 * total_cat_words[cat] / all_cat_words
            print(f"  {cat}: {per_review:.0f} words/review ({pct:.1f}%)")
        print(f"  Total: {all_cat_words/n:.0f} words/review")

    # Save results
    results = {
        "overview": {
            "total_on_list": total,
            "reviewed": reviewed_count,
            "with_findings": with_findings,
            "analyzed": len(per_review_data),
        },
        "content_breakdown": {
            "total_chars": total_all,
            "quoted_code_chars": total_quoted_chars,
            "commentary_chars": total_commentary_chars,
            "commentary_words": total_commentary_words,
        },
        "classification": {k: len(v) for k, v in category_findings.items()},
        "per_review": per_review_data,
    }
    out_path = os.path.join(cache_dir, "analysis_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    cache_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CACHE_DIR
    analyze_cache(cache_dir)
