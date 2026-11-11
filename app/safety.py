"""
app/safety.py
─────────────
Safety checks for the fixed HTML returned by the repair model.

A fixed file must pass all four checks before being saved:
  1. non_empty    – result is a non-empty string
  2. has_doctype  – starts with <!DOCTYPE (case-insensitive)
  3. has_body     – contains a <body> tag
  4. text_retention – at least 80% of the original visible text words
                      are still present in the fixed version

Public API
──────────
  check(original_html, fixed_html) -> SafetyResult
      Runs all checks and returns a SafetyResult dataclass.

  SafetyResult.ok   – True if all checks passed
  SafetyResult.failures – list of failed check names
  SafetyResult.details  – dict with per-check info (useful for logging)
"""

import re
from dataclasses import dataclass, field

# Minimum fraction of original text words that must survive
TEXT_RETENTION_THRESHOLD = 0.80


@dataclass
class SafetyResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    details:  dict      = field(default_factory=dict)

    def __str__(self) -> str:
        if self.ok:
            return f"SafetyResult(ok=True, retention={self.details.get('retention_ratio', '?'):.0%})"
        return f"SafetyResult(ok=False, failures={self.failures}, details={self.details})"


def _visible_words(html: str) -> list[str]:
    """
    Extract visible text words from HTML by stripping all tags and
    collapsing whitespace.  Returns a list of lower-cased words.
    This is intentionally simple — we only need an approximate word count,
    not a perfect parser.
    """
    # Remove <style> and <script> blocks entirely
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Strip all remaining tags
    html = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace and split
    words = re.split(r"\s+", html.lower())
    # Keep only words with at least 2 alphabetic characters
    return [w for w in words if re.search(r"[a-z]{2}", w)]


def check(original_html: str, fixed_html: str) -> SafetyResult:
    """
    Run all safety checks on the fixed HTML.

    Args:
        original_html: The original page source (before fixing).
        fixed_html:    The HTML returned by the repair model.

    Returns:
        SafetyResult with .ok, .failures, and .details.
    """
    failures = []
    details  = {}

    # ── Check 1: non-empty ────────────────────────────────────────────────────
    stripped = fixed_html.strip() if fixed_html else ""
    details["length"] = len(stripped)
    if not stripped:
        failures.append("non_empty")

    # ── Check 2: has DOCTYPE ──────────────────────────────────────────────────
    has_doctype = stripped.lower().startswith("<!doctype")
    details["has_doctype"] = has_doctype
    if not has_doctype:
        failures.append("has_doctype")

    # ── Check 3: has <body> tag ───────────────────────────────────────────────
    has_body = bool(re.search(r"<body[\s>]", stripped, re.IGNORECASE))
    details["has_body"] = has_body
    if not has_body:
        failures.append("has_body")

    # ── Check 4: text retention ≥ 80% ────────────────────────────────────────
    orig_words  = set(_visible_words(original_html))
    fixed_words = set(_visible_words(fixed_html)) if fixed_html else set()

    if orig_words:
        retained       = orig_words & fixed_words
        retention_ratio = len(retained) / len(orig_words)
    else:
        retention_ratio = 1.0  # empty original → vacuously satisfied

    details["orig_word_count"]   = len(orig_words)
    details["fixed_word_count"]  = len(fixed_words)
    details["retention_ratio"]   = retention_ratio
    details["missing_words"]     = sorted(orig_words - fixed_words)[:20]  # first 20 for log

    if retention_ratio < TEXT_RETENTION_THRESHOLD:
        failures.append("text_retention")

    ok = len(failures) == 0
    result = SafetyResult(ok=ok, failures=failures, details=details)

    if ok:
        print(f"[safety] ✓ all checks passed  (retention={retention_ratio:.0%}, length={len(stripped):,})")
    else:
        print(f"[safety] ✗ FAILED: {failures}  (retention={retention_ratio:.0%}, length={len(stripped):,})")
        if "text_retention" in failures:
            missing_preview = details["missing_words"][:10]
            print(f"[safety]   missing words sample: {missing_preview}")

    return result
