"""
app/try_loop.py
───────────────
CLI: run the full analyze → fix → verify loop on a demo site.

Usage:
    python -m app.try_loop demo1            # run one site
    python -m app.try_loop demo1 --fresh    # bypass disk cache, live API only
    python -m app.try_loop --all             # run all 3 demo sites
    python -m app.try_loop --all --fresh

The server must be running first:
    python -m uvicorn app.main:app --reload
"""

import asyncio
import json
import sys
from pathlib import Path

DEMO_SITES = {
    "demo1": "http://127.0.0.1:8000/demo-sites/demo1.html",
    "demo2": "http://127.0.0.1:8000/demo-sites/demo2.html",
    "demo3": "http://127.0.0.1:8000/demo-sites/demo3.html",
    "demo4": "http://127.0.0.1:8000/demo-sites/demo4.html",
}

_SEV    = {"high": "🔴", "medium": "🟡", "low": "🟢"}
_STOP   = {
    "all_fixed":      "✓ all fixed",
    "no_progress":    "⚠ no progress",
    "regression":     "⚠ regression",
    "max_rounds":     "⚠ max rounds",
    "safety_failure": "✗ safety failure",
    "":               "",
}


def _print_diagnosis(report: dict):
    """Print per-issue diagnosis: before/after DOM measurements + Spark evidence."""
    per_issue = report.get("per_issue", [])
    if not per_issue:
        return

    print(f"\n  Per-issue diagnosis:")
    print(f"  {'ID':<10} {'Status':<6} {'DomSig':<14} {'Spark':<6} {'Before → After':<30} {'Evidence'}")
    print(f"  {'─'*10} {'─'*6} {'─'*14} {'─'*6} {'─'*30} {'─'*40}")

    for r in per_issue:
        icon = "✓" if r["fixed"] else "✗"
        dom  = r.get("dom_signal", "?")
        spk  = "✓" if r.get("spark_signal") else "✗"

        before = r.get("dom_before") or "—"
        after  = r.get("dom_after")  or "—"
        ba    = f"{before} → {after}"

        ev = (r.get("spark_evidence") or "")[:40]
        print(f"  {r['id']:<10} {icon:<6} {dom:<14} {spk:<6} {ba:<30} {ev}")


def _print_ignored(report: dict):
    """Print ignored (decorative) elements."""
    ignored = report.get("ignored", [])
    if not ignored:
        return

    print(f"\n  Ignored (decorative — not counted as issues):")
    for ig in ignored:
        sel  = ig.get("selector", "?")
        typ  = ig.get("type", "?")
        reas = ig.get("ignore_reason", "?")
        val  = ig.get("measured_value", "")
        val_str = f" ({val})" if val != "" else ""
        print(f"    {typ:<20} {sel:<30} reason: {reas}{val_str}")


def _print_summary_one(report: dict, label: str):
    """Print the one-line summary banner for a single run."""
    found  = report["total_issues"]
    fixed  = report["total_fixed"]
    ign    = report.get("total_ignored", 0)
    rounds = report["rounds_used"]
    stop   = _STOP.get(report.get("stop_reason", ""), "")

    all_ok = fixed == found and found > 0
    tick   = "✓" if all_ok else ("⚠" if fixed > 0 else "✗")

    print(f"\n{'═'*55}")
    print(f"  {found} found,  {fixed} fixed,  {ign} ignored,  {rounds} round(s)  {tick}")
    if stop:
        print(f"  {stop}")
    print(f"{'═'*55}")


async def _run_one(url: str, label: str, fresh: bool) -> dict:
    """Run the loop on one URL and print results."""
    print(f"\n╔══════════════════════════════════════════════════════════════╗")
    print(f"║  VisualDetox — Verify Loop  [{label}]")
    print(f"║  fresh: {fresh}")
    print(f"╚══════════════════════════════════════════════════════════════╝\n")

    from app.loop import run_loop
    report = await run_loop(url=url, fresh=fresh)

    _print_summary_one(report, label)
    _print_diagnosis(report)
    _print_ignored(report)

    # File locations
    if report.get("fixed_html_url"):
        fixed_server = f"http://127.0.0.1:8000{report['fixed_html_url']}"
        from app.config import settings
        run_dir = Path(settings.OUTPUT_DIR) / report["run_id"]
        print(f"\n  Compare: {url}  →  {fixed_server}")
        print(f"  Run dir: {run_dir.resolve()}")

    return report


async def _run_all(fresh: bool):
    """Run all three demo sites and print a summary table."""
    results = []
    for label, url in DEMO_SITES.items():
        report = await _run_one(url, label, fresh)
        results.append((label, report))

    # Summary table
    print(f"\n\n{'='*70}")
    print(f"  SUMMARY TABLE — all demo sites")
    print(f"{'='*70}")
    print(f"  {'Site':<8} {'Found':<7} {'Fixed':<7} {'Ignored':<8} {'Rounds':<7} {'Stop Reason'}")
    print(f"  {'─'*8} {'─'*7} {'─'*7} {'─'*8} {'─'*7} {'─'*20}")

    for label, report in results:
        found  = report["total_issues"]
        fixed  = report["total_fixed"]
        ign    = report.get("total_ignored", 0)
        rounds = report["rounds_used"]
        stop   = _STOP.get(report.get("stop_reason", ""), "?")
        print(f"  {label:<8} {found:<7} {fixed:<7} {ign:<8} {rounds:<7} {stop}")

    print(f"{'='*70}\n")


async def main():
    args  = sys.argv[1:]
    fresh = "--fresh" in args
    all_mode = "--all" in args
    args  = [a for a in args if a not in ("--fresh", "--all")]
    arg   = args[0] if args else "demo1"

    if all_mode:
        await _run_all(fresh)
        return

    url = DEMO_SITES.get(arg, arg if arg.startswith("http") else None)
    if not url:
        print(f"Unknown argument: {arg!r}. Use demo1/demo2/demo3 or a full URL.")
        sys.exit(1)

    await _run_one(url, arg, fresh)


if __name__ == "__main__":
    asyncio.run(main())
