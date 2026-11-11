"""
app/e2e_test.py
───────────────
End-to-end tests for VisualDetox. Uses cached results / MOCK_MODE so no
API credits are spent.

Usage:
    python -m app.e2e_test

All tests must pass before touching the UI. Exit code 0 = all pass.

Tests
─────
  A. SSE stream for demo1/2/3: streams step events and ends with a done event.
  B. /api/runs returns labeled runs; /api/replay save+load works.
  C. Replay of featured run: every field the UI needs is present in the report.
  D. Error paths return a friendly message, never a raw Python traceback.
"""

import asyncio
import json
import sys
import time
import httpx

from app.config import settings

BASE = f"http://127.0.0.1:{settings.PORT}"
DEMO_URLS = {
    "demo1": f"{BASE}/demo-sites/demo1.html",
    "demo2": f"{BASE}/demo-sites/demo2.html",
    "demo3": f"{BASE}/demo-sites/demo3.html",
    "demo4": f"{BASE}/demo-sites/demo4.html",
}

# Fields that every loop_report the UI consumes must have
REQUIRED_REPORT_FIELDS = {
    "run_id", "url", "total_issues", "total_fixed", "rounds_used",
    "stop_reason", "fixed_html_url", "before_screenshots",
    "final_after_screenshots", "analysis_issues", "per_issue",
    "raw_findings_count", "ignored",
}

PASS = "PASS"
FAIL = "FAIL"


# ── helpers ────────────────────────────────────────────────────────────────────

def check(label: str, ok: bool, detail: str = "") -> bool:
    status = PASS if ok else FAIL
    print(f"  [{status}] {label}" + (f": {detail}" if detail else ""))
    return ok


async def stream_run(url: str, timeout: int = 120) -> tuple[list[dict], dict | None, str | None]:
    """
    POST /api/run/stream and collect all SSE events.
    Returns (step_events, done_report, error_message).
    Aborts after `timeout` seconds.
    """
    steps: list[dict] = []
    done_report = None
    error_msg = None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            async with client.stream(
                "POST", f"{BASE}/api/run/stream",
                json={"url": url, "fresh": False},
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status_code != 200:
                    return steps, None, f"HTTP {resp.status_code}"
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        event_str, buffer = buffer.split("\n\n", 1)
                        ev_type, ev_data = "message", ""
                        for line in event_str.split("\n"):
                            if line.startswith("event: "):
                                ev_type = line[7:].strip()
                            elif line.startswith("data: "):
                                ev_data = line[6:]
                        if not ev_data:
                            continue
                        try:
                            payload = json.loads(ev_data)
                        except json.JSONDecodeError:
                            continue
                        if ev_type == "step":
                            steps.append(payload)
                        elif ev_type == "done":
                            done_report = payload
                            return steps, done_report, None
                        elif ev_type == "error":
                            error_msg = payload.get("message", str(payload))
                            return steps, None, error_msg
    except Exception as exc:
        error_msg = str(exc)

    return steps, done_report, error_msg


# ── Test A: SSE stream ─────────────────────────────────────────────────────────

async def test_a_sse():
    print("\n── Test A: SSE stream for demo1/demo2/demo3 ──")
    all_ok = True
    for name, url in DEMO_URLS.items():
        print(f"\n  {name}: {url}")
        steps, report, err = await stream_run(url)

        got_steps = [s["step"] for s in steps]
        has_screenshotting = any(s["step"] == "screenshotting" for s in steps)
        has_done = check(f"{name}: stream ended with done event", report is not None,
                         f"error={err}" if err else "")
        has_ss   = check(f"{name}: received screenshotting step", has_screenshotting,
                         f"got steps: {got_steps[:5]}")
        no_traceback = True
        if err and ("Traceback" in err or "File " in err and "line " in err):
            no_traceback = False
        check(f"{name}: no Python traceback in error", no_traceback, err or "")
        all_ok = all_ok and has_done and has_ss and no_traceback
    return all_ok


# ── Test B: /api/runs and /api/replay ─────────────────────────────────────────

async def test_b_runs_replay():
    print("\n── Test B: /api/runs and /api/replay ──")
    all_ok = True

    async with httpx.AsyncClient(timeout=15) as client:
        # /api/runs
        resp = await client.get(f"{BASE}/api/runs")
        ok = check("GET /api/runs returns 200", resp.status_code == 200)
        all_ok = all_ok and ok
        if not ok:
            return False

        runs = resp.json().get("runs", [])
        check("runs list is non-empty", len(runs) > 0, f"got {len(runs)}")
        has_labels = all("label" in r for r in runs)
        check("every run has a label", has_labels)
        has_no_raw_ids = all(
            # label should not just be a hex run_id with no spaces
            " " in r.get("label", "") for r in runs
        )
        check("no raw run IDs as labels", has_no_raw_ids)
        all_ok = all_ok and has_labels and has_no_raw_ids

        # /api/replay save
        if runs:
            first = runs[0]
            rid = first["run_id"]
            site = first.get("site", "demo1")
            resp2 = await client.post(
                f"{BASE}/api/replay",
                json={"demo": site, "run_id": rid},
            )
            check("POST /api/replay returns 200", resp2.status_code == 200,
                  resp2.text[:80])
            # verify it was saved
            resp3 = await client.get(f"{BASE}/api/replay")
            saved = resp3.json()
            check("saved replay is retrievable", saved.get(site) == rid,
                  f"expected {rid}, got {saved.get(site)}")

    return all_ok


# ── Test C: replay report completeness ────────────────────────────────────────

async def test_c_report_fields():
    print("\n── Test C: replay report has all fields the UI needs ──")
    all_ok = True

    async with httpx.AsyncClient(timeout=15) as client:
        runs_resp = await client.get(f"{BASE}/api/runs")
        runs = runs_resp.json().get("runs", [])
        if not runs:
            check("at least one run exists for field check", False)
            return False

        # Check the most recent run
        run = runs[0]
        rid = run["run_id"]
        detail_resp = await client.get(f"{BASE}/api/run/{rid}")
        if detail_resp.status_code != 200:
            check(f"GET /api/run/{rid} returns 200", False, detail_resp.text[:80])
            return False

        report = detail_resp.json()
        missing = REQUIRED_REPORT_FIELDS - set(report.keys())
        check("no required fields missing", len(missing) == 0,
              f"missing: {missing}" if missing else "")
        all_ok = all_ok and (len(missing) == 0)

        # before_screenshots must have desktop and mobile
        bs = report.get("before_screenshots", {})
        check("before_screenshots has desktop", "desktop" in bs)
        check("before_screenshots has mobile",  "mobile"  in bs)
        all_ok = all_ok and ("desktop" in bs) and ("mobile" in bs)

        # per_issue must be a list
        pi = report.get("per_issue", None)
        check("per_issue is a list", isinstance(pi, list),
              type(pi).__name__ if not isinstance(pi, list) else f"{len(pi)} items")
        all_ok = all_ok and isinstance(pi, list)

    return all_ok


# ── Test D: error paths ────────────────────────────────────────────────────────

async def test_d_error_paths():
    print("\n── Test D: error paths return friendly messages, not tracebacks ──")
    all_ok = True

    async with httpx.AsyncClient(timeout=30) as client:
        # Bad URL — should return an error event, not a traceback
        _steps, _report, err = await stream_run("http://127.0.0.1:9999/no-such-page", timeout=30)
        has_err = check("bad URL produces an error event", err is not None, repr(err)[:60])
        if err:
            no_tb = (
                "Traceback" not in err
                and 'File "' not in err
                and "net::ERR_" not in err       # raw Playwright network errors
                and "Call log:" not in err        # raw Playwright call log
            )
            check("error message has no Python traceback or Playwright dump", no_tb, err[:120])
            all_ok = all_ok and no_tb
        all_ok = all_ok and has_err

        # /api/run/{bad_id} → 404
        resp = await client.get(f"{BASE}/api/run/nonexistent_run_abc123")
        check("unknown run_id returns 404", resp.status_code == 404)
        all_ok = all_ok and (resp.status_code == 404)

    return all_ok


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("VisualDetox e2e tests (no API credits spent)")
    print("=" * 60)

    # Quick server check
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            h = await c.get(f"{BASE}/health")
            info = h.json()
            print(f"\nServer: {info['status']}  mock={info['mock_mode']}  key={info['api_key_set']}")
    except Exception as exc:
        print(f"\n✗ Server not reachable at {BASE}: {exc}")
        print("  Start it with:  python -m uvicorn app.main:app --reload")
        sys.exit(1)

    results = {}
    results["A"] = await test_a_sse()
    results["B"] = await test_b_runs_replay()
    results["C"] = await test_c_report_fields()
    results["D"] = await test_d_error_paths()

    print(f"\n{'='*60}")
    all_passed = all(results.values())
    for k, v in results.items():
        print(f"  Test {k}: {'PASS' if v else 'FAIL'}")
    print(f"{'='*60}")
    if all_passed:
        print("All tests passed.")
    else:
        print("Some tests FAILED — see output above.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
