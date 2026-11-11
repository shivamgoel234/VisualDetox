"""
app/try_analyze.py
──────────────────
CLI tool to run the Phase 2 analyzer on a demo site and print results.

Usage:
    python -m app.try_analyze demo1
    python -m app.try_analyze demo2
    python -m app.try_analyze demo3
    python -m app.try_analyze http://example.com   (any URL)

The server must be running:
    uvicorn app.main:app --reload
"""

import asyncio
import sys
from pathlib import Path

# Demo site map — short names → server URLs
DEMO_SITES = {
    "demo1": "http://127.0.0.1:8000/demo-sites/demo1.html",
    "demo2": "http://127.0.0.1:8000/demo-sites/demo2.html",
    "demo3": "http://127.0.0.1:8000/demo-sites/demo3.html",
}


def _severity_icon(sev: str) -> str:
    return {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")


async def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "demo1"

    # Resolve to a URL
    if arg.startswith("http"):
        url = arg
    elif arg in DEMO_SITES:
        url = DEMO_SITES[arg]
    else:
        print(f"Unknown demo site: {arg!r}")
        print(f"Valid options: {', '.join(DEMO_SITES)}")
        sys.exit(1)

    print(f"Running Phase 2 analyzer on: {url}\n")

    from app.analyzer import analyze
    report = await analyze(url)

    # ── Print summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"  Run ID    : {report['run_id']}")
    print(f"  URL       : {report['url']}")
    print(f"  Mock mode : {report['mock_mode']}")
    print(f"  DOM finds : {len(report['dom_findings'])}")
    print(f"  Issues    : {len(report['issues'])}")
    print("=" * 65)

    # ── DOM findings ──────────────────────────────────────────────────────────
    if report["dom_findings"]:
        print(f"\n  DOM Checks ({len(report['dom_findings'])} findings):")
        for f in report["dom_findings"]:
            vp = f.get("viewport", "?")
            print(f"    [{vp:7}] {f['type']:22} {f['selector'][:40]}")
            print(f"             {f['description'][:70]}")

    # ── Issues ────────────────────────────────────────────────────────────────
    print(f"\n  Issues found ({len(report['issues'])}):")
    for iss in report["issues"]:
        icon  = _severity_icon(iss["severity"])
        ann   = iss.get("annotation", {})
        method = ann.get("method", "none")
        boxes  = ann.get("boxes", [])
        ann_path = Path(ann.get("path", "")).name if ann.get("path") else "—"

        print(f"\n  {icon} [{iss['id']}]  severity={iss['severity']}  viewport={iss['viewport']}")
        print(f"     desc       : {iss['description']}")
        print(f"     Element : {iss['element_description']!r}")
        print(f"     annotation : method={method}  boxes={len(boxes)}  file={ann_path}")

    # ── File locations ────────────────────────────────────────────────────────
    run_dir = Path(report["screenshots"]["desktop"]).parent
    print(f"\n  Output directory: {run_dir.resolve()}")
    print(f"  Desktop screenshot : {Path(report['screenshots']['desktop']).name}")
    print(f"  Mobile  screenshot : {Path(report['screenshots']['mobile']).name}")
    print(f"  Report JSON        : report.json")

    annotated = [
        Path(iss["annotation"]["path"]).name
        for iss in report["issues"]
        if iss.get("annotation", {}).get("method") != "none"
    ]
    if annotated:
        print(f"  Annotated PNGs     : {', '.join(annotated)}")

    print("\nDone.\n")


if __name__ == "__main__":
    asyncio.run(main())
