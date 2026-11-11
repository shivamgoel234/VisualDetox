"""Verify a proposed repair using screenshots and DOM measurements."""

import asyncio
from pathlib import Path

from app.config     import settings
from app.screenshot import capture_viewports
from app.models import verify_fixes


# DOM finding types and which field in `extra` carries the main metric
_DOM_TYPE_METRIC = {
    "low_contrast":        ("contrast_ratio", lambda v: v >= 4.5),
    "horizontal_overflow": ("overflow_px",    lambda v: v <= 0),
    "overlapping_text":    (None,             lambda v: False),   # presence = still broken
    "outside_viewport":    (None,             lambda v: False),
}


def _dom_is_clean(
    dom_type: str,
    dom_selector: str,
    after_findings: list[dict],
    before_findings: list[dict] | None = None,
) -> tuple[str, dict]:
    """
    Check whether a specific DOM issue has disappeared in the after findings.

    Returns:
        (signal, measurements)
        signal: "fixed" | "not_fixed" | "inconclusive"
        measurements: {"before": str|None, "after": str|None}
    """
    if not dom_type:
        return ("inconclusive", {"before": None, "after": None})

    # Find the BEFORE measurement for this issue
    before_val = None
    if before_findings:
        for f in before_findings:
            if f.get("type") != dom_type:
                continue
            f_sel = f.get("selector", "")
            if dom_selector and (f_sel == dom_selector or
                                 dom_selector in f_sel or
                                 f_sel in dom_selector):
                before_val = f.get("extra", {}).get("measurement", str(f.get("extra", {}).get("measured_value", "?")))
                break

    # Look for surviving finding of the same type affecting the same selector
    for f in after_findings:
        if f.get("type") != dom_type:
            continue
        f_sel = f.get("selector", "")
        if dom_selector and (f_sel == dom_selector or
                             dom_selector in f_sel or
                             f_sel in dom_selector):
            after_val = f.get("extra", {}).get("measurement", str(f.get("extra", {}).get("measured_value", "?")))
            return ("not_fixed", {"before": before_val, "after": after_val})

    return ("fixed", {"before": before_val, "after": None})


async def verify(
    fix_report: dict,
    before_screenshots: dict,
    run_id: str,
    round_num: int = 1,
    before_dom_findings: list[dict] | None = None,
    on_progress=None,
) -> dict:
    """
    Verify every issue in fix_report against the fixed HTML.

    Args:
        fix_report:         The dict returned by fixer.fix().
        before_screenshots: Paths to the BEFORE desktop/mobile PNGs.
        run_id:             Run identifier (for saving after screenshots).
        round_num:          Which fix round this is (1-indexed). Used to
                            name screenshots and namespace the verify cache key.

    Returns a verify_report dict:
    {
        "run_id":           str,
        "round_num":        int,
        "after_screenshots":{"desktop": str, "mobile": str},
        "after_dom_findings": [...],
        "results": [
            {
                "id":           str,
                "description":  str,
                "dom_signal":   "fixed" | "not_fixed" | "inconclusive",
                "spark_signal": True | False,
                "spark_evidence": str,
                "fixed":        bool,   # True only if both signals agree
                "signals_agreed": bool,
            },
            ...
        ],
        "fixed_count":   int,
        "unfixed_count": int,
        "unfixed_issues": [...]   # full issue dicts for the next round's fixer
    }
    """
    fixed_url  = f"http://127.0.0.1:{_server_port()}/output/{run_id}/fixed.html"
    after_prefix = f"after_r{round_num}"

    print(f"\n[verifier] round={round_num}  loading {fixed_url}")

    from time import monotonic

    started = monotonic()
    if on_progress:
        await on_progress("verifying", "started", round=round_num)
    after_shots, measurements = await capture_viewports(fixed_url, run_id, after_prefix)
    after_dom = [
        {**finding, "viewport": viewport}
        for viewport, checks in measurements.items()
        for finding in checks["findings"]
    ]
    after_ig = [item for checks in measurements.values() for item in checks["ignored"]]
    issues_sent = fix_report.get("issues_sent", [])
    fields = {"id", "severity", "description", "element_description", "viewport"}
    visual_checks = {}

    if not settings.MOCK_MODE:
        for viewport in ("desktop", "mobile"):
            issues = [
                {key: value for key, value in issue.items() if key in fields}
                for issue in issues_sent
                if issue.get("viewport", "both") in (viewport, "both")
            ]
            if not issues:
                continue
            verdicts = await asyncio.to_thread(
                verify_fixes,
                Path(before_screenshots[viewport]).read_bytes(),
                after_shots[viewport].read_bytes(),
                issues,
                round_num,
            )
            visual_checks[viewport] = {verdict["id"]: verdict for verdict in verdicts}

    # ── Step 4: Combine signals ───────────────────────────────────────────────
    results      = []
    unfixed_issues = []

    for issue in issues_sent:
        iid       = issue["id"]
        dom_type  = issue.get("dom_type")
        dom_sel   = issue.get("dom_selector", "")

        viewport = issue.get("viewport", "both")
        viewports = ("desktop", "mobile") if viewport == "both" else (viewport,)
        dom_signal, dom_measurements = _dom_is_clean(
            dom_type, dom_sel,
            [finding for finding in after_dom if finding["viewport"] in viewports],
            [finding for finding in (before_dom_findings or []) if finding["viewport"] in viewports],
        )

        if settings.MOCK_MODE:
            spark_signal = dom_signal == "fixed"
            spark_evidence = "Fixture repair evaluated using browser measurements."
        else:
            verdicts = [visual_checks.get(view, {}).get(iid, {}) for view in viewports]
            spark_signal = all(verdict.get("fixed") is True for verdict in verdicts)
            spark_evidence = " ".join(
                f"{view.capitalize()}: {verdict.get('evidence', 'No vision verdict returned.')}"
                for view, verdict in zip(viewports, verdicts)
            )

        is_fixed = dom_signal == "fixed" and spark_signal
        signals_agreed = (dom_signal == "fixed") == spark_signal

        row = {
            "id":              iid,
            "viewport":        viewport,
            "description":     issue.get("description", ""),
            "severity":        issue.get("severity", "low"),
            "dom_type":        dom_type,
            "dom_selector":    dom_sel,
            "dom_signal":      dom_signal,
            "dom_before":      dom_measurements.get("before"),
            "dom_after":       dom_measurements.get("after"),
            "spark_signal":    spark_signal,
            "spark_evidence":  spark_evidence,
            "fixed":           is_fixed,
            "signals_agreed":  signals_agreed,
        }
        results.append(row)

        if not is_fixed:
            # Enrich the issue with current measurement for the next fixer round
            enriched = dict(issue)
            if dom_measurements.get("after"):
                enriched["current_measurement"] = dom_measurements["after"]
            if dom_measurements.get("before"):
                enriched["original_measurement"] = dom_measurements["before"]
            unfixed_issues.append(enriched)

    fixed_count   = sum(1 for r in results if r["fixed"])
    unfixed_count = len(results) - fixed_count

    print(f"  Verdict: {fixed_count} fixed, {unfixed_count} not fixed")
    if on_progress: await on_progress("verifying", "done", round=round_num, elapsed=round(monotonic() - started, 1), fixed=fixed_count, unfixed=unfixed_count)

    return {
        "run_id":             run_id,
        "round_num":          round_num,
        "after_screenshots": {
            "desktop": str(after_shots["desktop"]),
            "mobile":  str(after_shots["mobile"]),
        },
        "after_dom_findings": after_dom,
        "after_ignored":      after_ig,
        "results":            results,
        "fixed_count":        fixed_count,
        "unfixed_count":      unfixed_count,
        "unfixed_issues":     unfixed_issues,
    }


def _server_port() -> int:
    """Return the configured server port from settings."""
    return settings.PORT
