"""
app/issue_merge.py
──────────────────
Deduplicate and merge the raw DOM findings + model findings into one
clean, capped issue list ready to send to the repair model.

Why this exists
───────────────
Spark and the DOM checker both flag the same problem (e.g. low contrast on
<h3>) independently, producing duplicate entries.  Sending duplicates to the
fixer wastes tokens and confuses the model.  This module collapses them.

Strategy
────────
1.  Promote every DOM finding that has no matching Spark issue into a
    synthetic normalized issue (so the fixer always sees one schema).
2.  Merge model findings that describe the same element — detected by
    matching the `element_description` field (after normalisation) or
    the DOM `selector`.
3.  Sort by severity (high → medium → low) then by id.
4.  Cap the final list at MAX_ISSUES (8) keeping the highest-severity ones.

Public API
──────────
    merge_issues(spark_issues, dom_findings) -> list[dict]
        Returns at most MAX_ISSUES clean issue dicts, each with keys:
        {id, severity, description, element_description, viewport,
         dom_bbox (optional), dom_type (optional)}
"""

import re
from typing import Optional

MAX_ISSUES = 8

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# DOM finding type → severity mapping (used when promoting DOM findings)
_DOM_SEVERITY = {
    "low_contrast":        "high",
    "horizontal_overflow": "high",
    "overlapping_text":    "medium",
    "outside_viewport":    "medium",
}

# DOM finding type → human description template
_DOM_DESCRIPTION = {
    "low_contrast":        "Text contrast ratio {contrast_ratio}:1 is below the WCAG AA minimum of 4.5:1.",
    "horizontal_overflow": "Element extends {overflow_px}px beyond the right edge of the viewport.",
    "overlapping_text":    "Two text elements overlap by {overlap_x}×{overlap_y}px.",
    "outside_viewport":    "Element is fully outside the visible viewport.",
}

# DOM finding type → SAM-friendly element_description template
_DOM_ELEMENT_DESC = {
    "low_contrast":        "low contrast text",
    "horizontal_overflow": "overflowing element",
    "overlapping_text":    "overlapping text",
    "outside_viewport":    "off-screen element",
}


def _normalise(text: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _dom_to_issue(finding: dict, issue_id: str) -> dict:
    """
    Promote a raw DOM finding to a normalized issue dict.
    """
    dtype = finding.get("type", "unknown")
    extra = finding.get("extra", {})

    # Fill the description template
    tmpl = _DOM_DESCRIPTION.get(dtype, finding.get("description", "DOM issue detected."))
    desc = tmpl.format(
        contrast_ratio=extra.get("contrast_ratio", "?"),
        overflow_px=extra.get("overflow_px", "?"),
        overlap_x=extra.get("overlap_px", {}).get("x", "?"),
        overlap_y=extra.get("overlap_px", {}).get("y", "?"),
    )

    return {
        "id":                  issue_id,
        "severity":            _DOM_SEVERITY.get(dtype, "medium"),
        "description":         desc,
        "element_description": _DOM_ELEMENT_DESC.get(dtype, "element"),
        "viewport":            finding.get("viewport", "both"),
        # Extra fields used by fixer / verifier (not sent to Spark)
        "dom_bbox":            finding.get("bbox"),
        "dom_viewport":        finding.get("viewport"),
        "dom_type":            dtype,
        "dom_selector":        finding.get("selector"),
    }


def _issues_overlap(a: dict, b: dict) -> bool:
    """
    True if two issues clearly describe the same element.
    Checks:
      • normalised element_description is identical or one contains the other
      • normalised description shares ≥ 3 significant words
    """
    if a.get("dom_type") and b.get("dom_type"):
        return (a["dom_type"], a.get("dom_selector")) == (b["dom_type"], b.get("dom_selector"))

    a_elem = _normalise(a.get("element_description", ""))
    b_elem = _normalise(b.get("element_description", ""))

    if a_elem and b_elem:
        if a_elem == b_elem:
            return True
        if a_elem in b_elem or b_elem in a_elem:
            return True

    # Word-overlap heuristic on description
    a_words = set(_normalise(a.get("description", "")).split()) - {"the", "a", "an", "is", "are", "of", "in", "on", "to"}
    b_words = set(_normalise(b.get("description", "")).split()) - {"the", "a", "an", "is", "are", "of", "in", "on", "to"}
    common = a_words & b_words
    return len(common) >= 3


def _merge_pair(primary: dict, secondary: dict) -> dict:
    """
    Merge secondary into primary.  Primary wins on id / element_description.
    Secondary's dom_bbox is kept if primary has none.
    Severity is the higher of the two.
    """
    merged = dict(primary)

    # Take the worse (lower number = worse) severity
    if _SEVERITY_ORDER.get(secondary.get("severity", "low"), 2) < \
       _SEVERITY_ORDER.get(merged.get("severity", "low"), 2):
        merged["severity"] = secondary["severity"]

    # Prefer to have a DOM bbox
    if not merged.get("dom_bbox") and secondary.get("dom_bbox"):
        merged["dom_bbox"]    = secondary["dom_bbox"]
        merged["dom_viewport"] = secondary.get("dom_viewport")
        merged["dom_type"]    = secondary.get("dom_type")
        merged["dom_selector"] = secondary.get("dom_selector")

    # Append viewport info
    vps = {merged.get("viewport", "both"), secondary.get("viewport", "both")}
    if "desktop" in vps and "mobile" in vps:
        merged["viewport"] = "both"

    return merged


def merge_issues(
    spark_issues: list[dict],
    dom_findings: list[dict],
    renumber: bool = True,
) -> list[dict]:
    """
    Merge model findings and DOM findings into one deduplicated, capped list.

    Args:
        spark_issues:  Issues from the vision model().
        dom_findings:  Findings from run_dom_checks() (desktop + mobile merged).
        renumber:      If True (default), renumber IDs sequentially issue-1…N.
                       If False, preserve original issue IDs (used in round 2+
                       so the verifier can track issues across rounds).

    Returns:
        A list of at most MAX_ISSUES issue dicts, sorted high→medium→low.
    """
    # ── Step 1: Start with model findings (they have the best descriptions) ─────
    merged: list[dict] = []
    for issue in spark_issues:
        issue = dict(issue)                # copy so we don't mutate caller's data
        issue.setdefault("dom_bbox",       None)
        issue.setdefault("dom_type",       None)
        issue.setdefault("dom_selector",   None)
        merged.append(issue)

    # ── Step 2: Attach DOM bbox to matching model findings ──────────────────────
    #   (Helps annotate.py fall back to the right bbox; doesn't create new issues)
    used_dom_indices: set[int] = set()

    for issue in merged:
        if issue.get("dom_bbox"):          # already has one
            continue
        for i, finding in enumerate(dom_findings):
            if i in used_dom_indices:
                continue
            # Loose match: DOM selector word appears in issue description or elem_desc
            sel = finding.get("selector", "").lower()
            desc_lower = issue.get("description", "").lower()
            elem_lower = issue.get("element_description", "").lower()
            if sel and (sel in desc_lower or sel in elem_lower):
                issue["dom_bbox"]     = finding.get("bbox")
                issue["dom_type"]     = finding.get("type")
                issue["dom_selector"] = sel
                used_dom_indices.add(i)
                break

    # ── Step 3: Promote DOM findings with NO matching Spark issue ─────────────
    next_id = len(merged) + 1
    for i, finding in enumerate(dom_findings):
        if i in used_dom_indices:
            continue
        candidate = _dom_to_issue(finding, f"issue-{next_id}")
        # Check if it already overlaps with a Spark issue
        overlaps = any(_issues_overlap(candidate, existing) for existing in merged)
        if not overlaps:
            merged.append(candidate)
            used_dom_indices.add(i)
            next_id += 1

    # ── Step 4: Deduplicate within model findings themselves ────────────────────
    deduped: list[dict] = []
    for candidate in merged:
        absorbed = False
        for existing in deduped:
            if _issues_overlap(candidate, existing):
                # Merge candidate into existing in-place
                upgraded = _merge_pair(existing, candidate)
                deduped[deduped.index(existing)] = upgraded
                absorbed = True
                break
        if not absorbed:
            deduped.append(candidate)

    # ── Step 5: Sort high → medium → low, then cap ───────────────────────────
    deduped.sort(key=lambda x: _SEVERITY_ORDER.get(x.get("severity", "low"), 2))
    capped = deduped[:MAX_ISSUES]

    # Re-number ids sequentially so the fixer always sees issue-1 … issue-N
    if renumber:
        for idx, issue in enumerate(capped, start=1):
            issue["id"] = f"issue-{idx}"

    print(
        f"[issue_merge] {len(spark_issues)} Spark + {len(dom_findings)} DOM "
        f"→ {len(deduped)} merged → {len(capped)} after cap"
    )
    return capped
