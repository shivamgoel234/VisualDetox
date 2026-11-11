"""
app/try_fix.py
──────────────
CLI: run analyze + fix on a demo site and print where fixed.html lives.

Usage:
    python -m app.try_fix demo1
    python -m app.try_fix demo2
    python -m app.try_fix demo3
    python -m app.try_fix http://127.0.0.1:8000/demo-sites/demo1.html

The server must be running first:
    uvicorn app.main:app --reload
"""

import asyncio
import sys
from pathlib import Path

DEMO_SITES = {
    "demo1": "http://127.0.0.1:8000/demo-sites/demo1.html",
    "demo2": "http://127.0.0.1:8000/demo-sites/demo2.html",
    "demo3": "http://127.0.0.1:8000/demo-sites/demo3.html",
}

_SEV = {"high": "🔴", "medium": "🟡", "low": "🟢"}


async def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "demo1"
    url = DEMO_SITES.get(arg, arg if arg.startswith("http") else None)
    if not url:
        print(f"Unknown argument: {arg!r}. Use demo1/demo2/demo3 or a full URL.")
        sys.exit(1)

    print(f"╔══════════════════════════════════════════════════════════════╗")
    print(f"║  VisualDetox — Phase 3 Fix  ({arg})                ")
    print(f"╚══════════════════════════════════════════════════════════════╝\n")

    # ── Step A: Analyze ───────────────────────────────────────────────────────
    from app.analyzer import analyze
    from app.fixer    import fix

    print("── Phase 2: Analyze ──────────────────────────────────────────")
    analysis = await analyze(url)

    print(f"\n  Found {len(analysis['issues'])} issue(s) from Spark")
    print(f"  Found {len(analysis['dom_findings'])} DOM finding(s)")

    # ── Step B: Fix ───────────────────────────────────────────────────────────
    print("\n── Phase 3: Fix ──────────────────────────────────────────────")
    report = await fix(analysis)

    # ── Print results ─────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  Run ID        : {report['run_id']}")
    print(f"  Issues sent   : {report['issues_count']}")
    print(f"  Safety OK     : {'✓' if report['safety_ok'] else '✗'}")
    print(f"  Retried       : {'yes' if report['retried'] else 'no'}")

    if report.get("error"):
        print(f"\n  ⚠  ERROR: {report['error']}")

    safety = report.get("safety", {})
    if safety:
        print(f"\n  Safety details:")
        print(f"    Text retention : {safety.get('retention_ratio', 0):.0%}")
        print(f"    Fixed length   : {safety.get('length', '?'):,} chars")
        if safety.get("missing_words"):
            print(f"    Missing words  : {safety['missing_words'][:8]}")

    print(f"\n  Issues sent for fixing:")
    for iss in report.get("issues_sent", []):
        icon = _SEV.get(iss.get("severity", "low"), "⚪")
        print(f"    {icon} [{iss['id']}] {iss['description'][:70]}")

    if report.get("fixed_html_path"):
        fixed_path = Path(report["fixed_html_path"])
        fixed_url  = f"http://127.0.0.1:8000{report['fixed_html_url']}"

        print(f"\n{'='*65}")
        print(f"  ✓  Fixed file saved!")
        print(f"\n  Open in your browser to compare:")
        print(f"  Original : {url}")
        print(f"  Fixed    : {fixed_url}")
        print(f"\n  Or open the file directly:")
        print(f"  {fixed_path.resolve()}")
        print(f"\n  Run directory (screenshots + annotated PNGs + reports):")
        print(f"  {fixed_path.parent.resolve()}")
    else:
        print(f"\n  ✗  No fixed.html was saved — see error above.")

    print(f"{'='*65}\n")


if __name__ == "__main__":
    asyncio.run(main())
