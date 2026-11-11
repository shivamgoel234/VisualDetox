"""Propose a repair and check that it preserves the original page."""

import asyncio
import json
from pathlib import Path

import httpx

from app.config      import settings
from app.models import fix_code
from app.analyzer import demo_file
from app.safety      import check as safety_check


async def _fetch_html(url: str) -> str:
    demo = demo_file(url)
    if demo is not None:
        return demo.read_text(encoding="utf-8")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


async def fix(
    analysis_report: dict,
    html_override: str | None = None,
    on_progress=None,
    round_num: int = 1,
) -> dict:
    """
    Run the Phase 3 fix pipeline on a completed analysis report.

    Args:
        analysis_report: The dict returned by analyzer.analyze().
        html_override:   If provided, use this HTML string instead of fetching
                         the original URL.  Used by the verify loop for round 2+
                         where the input is the previous round's fixed.html.

    Returns a fix_report dict:
    {
        "run_id":          str,
        "url":             str,
        "fixed_html_path": str,
        "fixed_html_url":  str,
        "issues_sent":     list[dict],
        "issues_count":    int,
        "safety":          dict,
        "safety_ok":       bool,
        "retried":         bool,
        "error":           str | None,
    }
    """
    run_id = analysis_report["run_id"]
    url    = analysis_report["url"]
    out_dir = Path(settings.OUTPUT_DIR) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"[fixer] run_id={run_id}")
    print(f"{'='*60}")

    merged = analysis_report.get("issues", [])

    # Strip internal-only keys before sending to the model
    # (dom_bbox etc. are for our use, not for Spark)
    # Round 2+ issues carry current_measurement / original_measurement from
    # the verifier — include those so Spark knows what's still wrong.
    _spark_keys = {"id", "severity", "description", "element_description",
                   "viewport", "current_measurement", "original_measurement"}
    issues_for_spark = [
        {k: v for k, v in issue.items() if k in _spark_keys}
        for issue in merged
    ]

    # Build a precise fix-context for each open issue in round 2+
    # Include: selector, exact current measurement, target, and the
    # CSS rules that currently apply to that selector in the HTML being fixed.
    for iss in issues_for_spark:
        ctx_parts = []
        sel = next((m.get("dom_selector") for m in merged if m["id"] == iss["id"]), None)
        dom_type = next((m.get("dom_type") for m in merged if m["id"] == iss["id"]), None)

        if sel:
            ctx_parts.append(f"selector: {sel}")

        cur = iss.get("current_measurement", "")
        orig = iss.get("original_measurement", "")
        if cur:
            ctx_parts.append(f"current measurement: {cur}")
        if orig:
            ctx_parts.append(f"original measurement: {orig}")

        # Add the target explicitly per issue type
        if dom_type == "horizontal_overflow":
            ctx_parts.append("target: 0px overflow — element must not extend beyond viewport width")
        elif dom_type == "outside_viewport":
            ctx_parts.append("target: element must not be clipped off left/right viewport edges")
        elif dom_type == "low_contrast":
            ctx_parts.append("target: contrast ratio ≥4.5:1 (WCAG AA)")

        # Extract the CSS rules currently in the HTML that mention this selector
        if html_override and sel:
            import re
            # Strip the tag part if any (e.g. "div.menu-grid" → ".menu-grid" or "div.menu-grid")
            css_sel_variants = [sel]
            tag_match = re.match(r'^([a-z]+)([\.\#].+)?$', sel)
            if tag_match and tag_match.group(2):
                css_sel_variants.append(tag_match.group(2))   # class/id only variant

            current_rules = []
            for variant in css_sel_variants:
                escaped = re.escape(variant)
                # Find CSS blocks that reference this selector
                blocks = re.findall(
                    r'[^}]*' + escaped + r'[^{]*\{[^}]+\}',
                    html_override,
                    flags=re.DOTALL,
                )
                for b in blocks[:3]:   # max 3 blocks to stay concise
                    cleaned = re.sub(r'\s+', ' ', b.strip())[:300]
                    current_rules.append(cleaned)

            if current_rules:
                ctx_parts.append("current CSS: " + " | ".join(current_rules[:2]))

        if ctx_parts:
            iss["fix_context"] = " · ".join(ctx_parts)

    print(f"  Preparing {len(issues_for_spark)} issue(s) for repair")

    # ── Step 2: Fetch / receive original HTML ────────────────────────────────
    if html_override is not None:
        original_html = html_override
        print(f"\n[2/3] Using supplied HTML ({len(original_html):,} chars)")
    else:
        print(f"\n[2/3] Fetching original HTML from {url}…")
        original_html = await _fetch_html(url)
        (out_dir / "original.html").write_text(original_html, encoding="utf-8")
        print(f"  {len(original_html):,} chars")

    # ── Step 3: Fix → safety check → retry once ──────────────────────────────
    print("\n[3/3] Preparing repaired HTML…")
    if on_progress: await on_progress("fixing", "started", round=round_num)
    import time as _t; _t0 = _t.time()
    retried   = False
    error_msg = None
    safety_result = None
    fixed_html = ""

    for attempt in range(1, 3):
        if attempt == 2:
            print("[fixer] Safety check failed on attempt 1 — retrying the repair model…")
            retried = True

        if settings.MOCK_MODE:
            demo = demo_file(url)
            if demo is None:
                raise ValueError("Fixture repairs require a bundled demo page.")
            fixture_ids = {
                "demo1": "b486c55b", "demo2": "eef541d9",
                "demo3": "15fe1fa6", "demo4": "75afaa44",
            }
            saved = settings.DEMO_DIR.parent / "sample_runs" / fixture_ids[demo.stem] / "fixed.html"
            fixed_html = saved.read_text(encoding="utf-8")
        else:
            feedback = ", ".join(safety_result.failures) if safety_result else ""
            fixed_html = await asyncio.to_thread(fix_code, original_html, issues_for_spark, feedback=feedback)

        safety_result = safety_check(original_html, fixed_html)

        if safety_result.ok:
            break
        else:
            print(f"[fixer] Attempt {attempt} safety failures: {safety_result.failures}")
            if attempt == 2:
                error_msg = (
                    f"Fixed HTML failed safety checks after 2 attempts. "
                    f"Failures: {safety_result.failures}"
                )
                print(f"[fixer] ✗ {error_msg}")

    # Publish only a repair that passed the structural checks.
    fixed_path = out_dir / "fixed.html"
    if fixed_html and safety_result and safety_result.ok:
        fixed_path.write_text(fixed_html, encoding="utf-8")
        print(f"[fixer] Saved → {fixed_path}")
    elif not fixed_html:
        error_msg = "The repair returned an empty response."
        print(f"[fixer] ✗ {error_msg}")

    usable = bool(fixed_html and safety_result and safety_result.ok)
    fixed_html_url = f"/output/{run_id}/fixed.html"

    fix_report = {
        "run_id":          run_id,
        "url":             url,
        "fixed_html_path": str(fixed_path) if usable else None,
        "fixed_html_url":  fixed_html_url if usable else None,
        "issues_sent":     merged,          # full dicts with dom_bbox etc.
        "issues_count":    len(merged),
        "safety":          safety_result.details if safety_result else {},
        "safety_ok":       safety_result.ok       if safety_result else False,
        "retried":         retried,
        "error":           error_msg,
    }

    # Persist fix report alongside the other run artefacts
    report_path = out_dir / "fix_report.json"
    report_path.write_text(json.dumps(fix_report, indent=2, default=str))
    print(f"[fixer] Fix report saved → {report_path}")
    if on_progress: await on_progress("fixing", "done", round=round_num, elapsed=round(_t.time()-_t0, 1))

    return fix_report
