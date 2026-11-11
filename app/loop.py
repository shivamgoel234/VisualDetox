"""Run the audit, repair, and verification loop."""

import json
from pathlib import Path

from app.config   import settings
from app.analyzer import analyze
from app.fixer    import fix
from app.verifier import verify
from app.models import fresh_run

MAX_ROUNDS = 4
# No-progress stop requires this many consecutive rounds with no improvement
NO_PROGRESS_THRESHOLD = 2


async def run_loop(
    url:     str,
    run_id:  str | None = None,
    fresh:   bool       = False,
    on_progress=None,
) -> dict:
    token = fresh_run.set(fresh)
    try:
        return await _run_loop(url, run_id, on_progress)
    finally:
        fresh_run.reset(token)


async def _run_loop(url: str, run_id: str | None, on_progress) -> dict:
    analysis = await analyze(url, run_id=run_id, on_progress=on_progress)
    run_id   = analysis["run_id"]          # use the id that was actually assigned
    out_dir  = Path(settings.OUTPUT_DIR) / run_id

    # Capture before screenshots (Paths) for every verify round
    before_shots = {
        "desktop": Path(analysis["screenshots"]["desktop"]),
        "mobile":  Path(analysis["screenshots"]["mobile"]),
    }
    # Original DOM findings — used by verifier to show before/after measurements
    before_dom_findings = analysis.get("dom_findings", [])
    # Ignored (decorative) elements — carried through to the report
    ignored_findings = analysis.get("dom_ignored", [])

    total_issues = len(analysis["issues"])
    print(f"\n  Total issues found: {total_issues}")
    print(f"  Ignored (decorative): {len(ignored_findings)}")

    # Check if there's actually anything to fix: even if Spark found 0 issues,
    # the DOM findings alone may be enough to promote into issues.
    if total_issues == 0:
        print("  No issues — nothing to fix.")
        report = _make_report(
            run_id=run_id, url=url, total_issues=0,
            rounds_used=0, round_reports=[],
            fixed_html_url=None, error=None,
            ignored=ignored_findings,
            analysis=analysis,
            raw_findings_count=len(analysis.get("dom_findings", [])),
        )
        _save_report(out_dir, report)
        return report

    # ── Loop state ────────────────────────────────────────────────────────────
    round_reports:  list[dict] = []
    current_html:   str | None = None
    prev_unfixed:   int        = total_issues
    best_html:      str | None = None
    best_unfixed = total_issues + 1
    best_round = None
    first_issues = analysis["issues"]
    stop_reason:    str        = "max_rounds"
    stale_rounds:   int        = 0   # consecutive rounds with no improvement

    # We need the analysis report each round so the fixer can merge issues.
    # On rounds 2+ we swap in only the unfixed issues to keep the prompt short.
    current_analysis = analysis

    max_rounds = 1 if settings.MOCK_MODE else MAX_ROUNDS
    for round_num in range(1, max_rounds + 1):
        print(f"\n{'─'*60}")
        print(f"  ROUND {round_num}/{max_rounds}")
        print(f"{'─'*60}")

        # ── Fix ───────────────────────────────────────────────────────────────
        fix_report = await fix(
            analysis_report=current_analysis,
            html_override=current_html,     # None on round 1
            on_progress=on_progress,
            round_num=round_num,
        )

        if not fix_report.get("safety_ok") or not fix_report.get("fixed_html_path"):
            stop_reason = "safety_failure"
            print(f"  ✗ Safety check failed — aborting loop.")
            round_reports.append({"round": round_num, "fix": fix_report,
                                   "verify": None, "stop_reason": stop_reason})
            break

        # Read the fixed HTML for potential next round
        fixed_path = Path(fix_report["fixed_html_path"])
        fixed_html = fixed_path.read_text(encoding="utf-8")

        # ── Verify ────────────────────────────────────────────────────────────
        verify_report = await verify(
            fix_report={**fix_report, "issues_sent": first_issues},
            before_screenshots=before_shots,
            run_id=run_id,
            round_num=round_num,
            before_dom_findings=before_dom_findings,
            on_progress=on_progress,
        )

        round_reports.append({
            "round":  round_num,
            "fix":    fix_report,
            "verify": verify_report,
        })

        fixed_count   = verify_report["fixed_count"]
        unfixed_count = verify_report["unfixed_count"]
        after_dom_n   = len(verify_report["after_dom_findings"])

        print(f"\n  Round {round_num} result: "
              f"{fixed_count} fixed, {unfixed_count} still open")

        previous_dom_count = _get_prev_after_dom_n(round_reports, round_num)
        if round_num > 1 and after_dom_n > previous_dom_count:
            stop_reason = "regression"
            break

        if unfixed_count < best_unfixed:
            best_unfixed = unfixed_count
            best_html = fixed_html
            best_round = round_num

        if unfixed_count == 0:
            stop_reason = "all_fixed"
            break

        if settings.MOCK_MODE:
            stop_reason = "fixture_complete"
            break

        stale_rounds = stale_rounds + 1 if unfixed_count >= prev_unfixed else 0
        if stale_rounds >= NO_PROGRESS_THRESHOLD:
            stop_reason = "no_progress"
            break

        # ── Prepare next round ────────────────────────────────────────────────
        prev_unfixed = unfixed_count
        current_html = fixed_html    # next round operates on this round's output

        # Rebuild a minimal analysis-shaped dict with only unfixed issues,
        # so the fixer's merge step only re-sends what still needs fixing.
        unfixed_issues = verify_report["unfixed_issues"]
        current_analysis = {**analysis, "issues": unfixed_issues}

        print(f"  → Sending {len(unfixed_issues)} unfixed issue(s) to next round")

    fixed_html_url = None
    if best_html is not None:
        (out_dir / "fixed.html").write_text(best_html, encoding="utf-8")
        fixed_html_url = f"/output/{run_id}/fixed.html"

    report = _make_report(
        run_id=run_id,
        url=url,
        total_issues=total_issues,
        rounds_used=len(round_reports),
        round_reports=round_reports,
        fixed_html_url=fixed_html_url,
        error=round_reports[-1]["fix"].get("error") if stop_reason == "safety_failure" else None,
        stop_reason=stop_reason,
        total_fixed=total_issues - best_unfixed if best_round is not None else 0,
        ignored=ignored_findings,
        analysis=analysis,
        raw_findings_count=len(analysis["dom_findings"]),
        best_round=best_round,
    )
    _save_report(out_dir, report)

    # Turn off fresh mode when done

    return report


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_prev_after_dom_n(round_reports: list[dict], current_round: int) -> int:
    """Return the after_dom_findings count from the previous round."""
    for rr in reversed(round_reports):
        if rr["round"] < current_round and rr.get("verify"):
            return len(rr["verify"].get("after_dom_findings", []))
    return 0


def _make_report(
    run_id, url, total_issues, rounds_used, round_reports,
    fixed_html_url, error, stop_reason="", total_fixed=0,
    ignored=None, analysis=None, raw_findings_count=0, best_round=None,
) -> dict:
    """Assemble the final loop_report dict."""
    selected = next((row["verify"] for row in round_reports if row["round"] == best_round), None)
    per_issue = selected["results"] if selected else [
        {
            "id": issue["id"],
            "description": issue["description"],
            "viewport": issue["viewport"],
            "dom_signal": "inconclusive",
            "spark_signal": False,
            "fixed": False,
        }
        for issue in (analysis or {}).get("issues", [])
    ]

    # Analysis issues (with annotation paths) — used by the frontend to show
    # the annotated overlay images
    analysis_issues = []
    if analysis:
        for iss in analysis.get("issues", []):
            ann = iss.get("annotation", {})
            # Convert absolute path to /output/<run_id>/filename
            ann_path = ann.get("path", "")
            if ann_path:
                ann_path = f"/output/{run_id}/{Path(ann_path).name}"
            analysis_issues.append({
                "id":                  iss.get("id", ""),
                "severity":            iss.get("severity", ""),
                "description":         iss.get("description", ""),
                "element_description": iss.get("element_description", ""),
                "viewport":            iss.get("viewport", ""),
                "annotation_url":      ann_path,
                "annotation_method":   ann.get("method", "none"),
            })

    # Before + final after screenshot URLs
    before_shots = {}
    if analysis:
        for vp, p in analysis.get("screenshots", {}).items():
            before_shots[vp] = f"/output/{run_id}/{Path(p).name}"

    final_after_shots = {}
    if selected:
        for vp, p in selected["after_screenshots"].items():
            final_after_shots[vp] = f"/output/{run_id}/{Path(p).name}"

    return {
        "run_id":               run_id,
        "url":                  url,
        "mock_mode":             settings.MOCK_MODE,
        "total_issues":          total_issues,
        "total_fixed":           total_fixed,
        "total_ignored":         len(ignored) if ignored else 0,
        "ignored":               ignored or [],
        "raw_findings_count":    raw_findings_count,
        "rounds_used":           rounds_used,
        "stop_reason":           stop_reason,
        "fixed_html_url":        fixed_html_url,
        "before_screenshots":    before_shots,
        "final_after_screenshots": final_after_shots,
        "analysis_issues":       analysis_issues,
        "per_issue":             per_issue,
        "round_reports":         round_reports,
        "error":                 error,
    }


def _save_report(out_dir: Path, report: dict):
    """Write loop_report.json, serialising Path objects as strings."""
    path = out_dir / "loop_report.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n[loop] Report saved → {path}")
