"""FastAPI routes for VisualDetox."""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from app.analyzer import AuditInputError, DEMO_PATH, RUN_ID
from app.config import settings
from app.models import ModelError
from app.screenshot import browser_lifespan

logger = logging.getLogger(__name__)

for d in [settings.CACHE_DIR, settings.OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

app = FastAPI(
    title="VisualDetox",
    description="Visual QA and repair verification",
    version="0.5.0",
    lifespan=browser_lifespan,
)

demo_dir = os.path.abspath(settings.DEMO_DIR)
os.makedirs(demo_dir, exist_ok=True)
app.mount("/demo-sites", StaticFiles(directory=demo_dir, html=True), name="demo-sites")

class RunArtifacts(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.endswith(".html"):
            response.headers["Content-Security-Policy"] = (
                "sandbox; default-src 'none'; style-src 'unsafe-inline' https:; "
                "img-src data: https:; font-src data: https:; form-action 'none'; "
                "frame-ancestors 'none'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response


app.mount("/output", RunArtifacts(directory=settings.OUTPUT_DIR), name="output")
SAMPLE_RUNS_DIR = settings.DEMO_DIR.parent / "sample_runs"
app.mount("/sample-runs", RunArtifacts(directory=SAMPLE_RUNS_DIR), name="sample-runs")

static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

def _friendly_error(exc: Exception) -> str:
    """
    Convert a raw exception into a plain English message safe to show in the UI.
    The full traceback is logged server-side by the caller.
    """
    if isinstance(exc, (AuditInputError, ModelError)):
        return str(exc)
    msg = str(exc)
    # Network / connection errors
    if any(x in msg.lower() for x in ("connect", "connection", "err_connection", "refused")):
        return "Could not reach the page. Check the URL and try again."
    if "timeout" in msg.lower():
        return "The request timed out. The page may be slow or unreachable."
    # Playwright / screenshot errors — strip the verbose call log
    if any(x in msg.lower() for x in ("playwright", "browser", "page.goto", "net::")):
        return "Could not load the page. Make sure the URL is publicly reachable."
    # Safety check failures
    if "safety" in msg.lower() or "safety check" in msg.lower():
        return "Something went wrong while fixing the page. Try again."
    # Generic fallback — never expose a raw traceback
    return "Something went wrong. Check the server log for details."

SITE_NAMES = {"demo1": "Horizon Travel", "demo2": "LaunchPad", "demo3": "Craft Studio", "demo4": "Northwind Coffee"}


def _find_run_dir(run_id: str) -> Path | None:
    """
    Return the directory for a run_id, checking output/ first then sample_runs/.
    Returns None if not found in either.
    """
    if not RUN_ID.fullmatch(run_id):
        return None
    for base in (settings.OUTPUT_DIR, SAMPLE_RUNS_DIR):
        d = base / run_id
        if d.is_dir():
            return d
    return None

def _site_key(url: str) -> str:
    path = urlsplit(url).path
    return Path(path).stem if DEMO_PATH.fullmatch(path) else "custom"

def _load_meta() -> dict:
    """
    Load run metadata.  output/run_meta.json takes precedence (user's live runs).
    sample_runs/run_meta.json provides the committed default featured mapping.
    """
    # Start with sample_runs defaults
    base: dict = {"hidden": [], "featured": {}}
    sample_meta = SAMPLE_RUNS_DIR / "run_meta.json"
    if sample_meta.exists():
        try:
            base = json.loads(sample_meta.read_text())
        except json.JSONDecodeError:
            pass

    # Overlay with live output/ metadata (user's own stars/hides)
    live_meta = Path(settings.OUTPUT_DIR) / "run_meta.json"
    if live_meta.exists():
        try:
            live = json.loads(live_meta.read_text())
            # Merge: live featured wins per-site; live hidden adds to base
            for site, rid in live.get("featured", {}).items():
                base.setdefault("featured", {})[site] = rid
            base.setdefault("hidden", []).extend(
                h for h in live.get("hidden", []) if h not in base["hidden"]
            )
        except json.JSONDecodeError:
            pass
    return base

def _save_meta(meta: dict):
    """Save user metadata to output/ only — never overwrites sample_runs/."""
    Path(settings.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    (Path(settings.OUTPUT_DIR) / "run_meta.json").write_text(json.dumps(meta, indent=2))

def _run_label(report: dict, mtime: float) -> str:
    name = SITE_NAMES.get(_site_key(report.get("url", "")), "Custom")
    fixed = report.get("total_fixed", 0)
    found = report.get("total_issues", 0)
    rounds = report.get("rounds_used", 0)
    dt = datetime.fromtimestamp(mtime)
    t = dt.strftime("%I:%M %p")
    if t.startswith("0"): t = t[1:]
    return f"{name} · {fixed} of {found} fixed · {rounds} rounds · {dt.strftime('%b')} {dt.day}, {t}"


@app.get("/api/config")
async def frontend_config():
    """Serve non-secret settings the frontend needs (repo URL, site port, key status)."""
    return {
        "repo_url":    settings.REPO_URL,   # empty string if not set
        "port":        settings.PORT,
        "api_key_set": bool(settings.GEMINI_API_KEY),
        "mock_mode":   settings.MOCK_MODE,
    }


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/health")
async def health():
    return {
        "status":      "ok",
        "mock_mode":   settings.MOCK_MODE,
        "gemini_model": settings.GEMINI_MODEL,
        "api_key_set": bool(settings.GEMINI_API_KEY),
    }


class AnalyzeRequest(BaseModel):
    url: str
    run_id: str | None = None

@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest):
    from app.analyzer import analyze
    try:
        return await analyze(url=req.url, run_id=req.run_id)
    except Exception as exc:
        status = 422 if isinstance(exc, AuditInputError) else 502
        raise HTTPException(status_code=status, detail=_friendly_error(exc)) from exc


class FixRequest(BaseModel):
    url:    str
    run_id: str | None = None

@app.post("/api/fix")
async def api_fix(req: FixRequest):
    from app.analyzer import analyze
    from app.fixer    import fix
    try:
        analysis = await analyze(url=req.url, run_id=req.run_id)
        return await fix(analysis)
    except Exception as exc:
        status = 422 if isinstance(exc, AuditInputError) else 502
        raise HTTPException(status_code=status, detail=_friendly_error(exc)) from exc


class LoopRequest(BaseModel):
    url:    str
    run_id: str | None = None
    fresh:  bool       = False

@app.post("/api/loop")
async def api_loop(req: LoopRequest):
    from app.loop import run_loop
    try:
        return await run_loop(url=req.url, run_id=req.run_id, fresh=req.fresh)
    except Exception as exc:
        status = 422 if isinstance(exc, AuditInputError) else 502
        raise HTTPException(status_code=status, detail=_friendly_error(exc)) from exc


@app.post("/api/run/stream")
async def run_stream(req: LoopRequest):
    """
    Run the full loop and stream progress as Server-Sent Events.

    SSE events:
      event: step   data: {"step": "screenshotting", "status": "started"}
      event: step   data: {"step": "fixing", "status": "done", "round": 1, "elapsed": 15.9}
      event: done   data: {full loop_report}
      event: error  data: {"message": "..."}
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(step: str, status: str, **data):
        await queue.put({"event": "step", "data": {"step": step, "status": status, **data}})

    async def run_task():
        try:
            from app.loop import run_loop
            report = await run_loop(
                url=req.url, run_id=req.run_id, fresh=req.fresh,
                on_progress=on_progress,
            )
            await queue.put({"event": "done", "data": report})
        except Exception as exc:
            logger.exception("Audit failed")
            # Send a friendly message to the UI — no Python traceback
            friendly = _friendly_error(exc)
            await queue.put({"event": "error", "data": {"message": friendly}})

    task = asyncio.create_task(run_task())

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], default=str)}\n\n"
                if event["event"] in ("done", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs")
async def list_runs():
    """
    List saved runs newest-first, from output/ and sample_runs/.
    output/ runs come first (they have real mtimes); sample_runs/ provides
    fallback runs for a fresh clone with no output/ directory.
    """
    meta    = _load_meta()
    hidden  = set(meta.get("hidden", []))
    featured = meta.get("featured", {})
    seen_ids: set[str] = set()
    runs: list[dict]   = []

    # Gather from both directories; output/ first so it takes precedence
    dirs_to_scan: list[tuple[Path, str]] = []  # (dir_path, url_prefix)
    out = Path(settings.OUTPUT_DIR)
    if out.exists():
        dirs_to_scan.append((out, "/output"))
    if SAMPLE_RUNS_DIR.exists():
        dirs_to_scan.append((SAMPLE_RUNS_DIR, "/sample-runs"))

    for base_dir, url_prefix in dirs_to_scan:
        candidates = sorted(
            (d for d in base_dir.iterdir() if d.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for d in candidates:
            if d.name in hidden: continue
            rp = d / "loop_report.json"
            if not rp.exists(): continue
            try: report = json.loads(rp.read_text())
            except (json.JSONDecodeError, KeyError): continue
            found = report.get("total_issues", 0)
            if found == 0: continue
            rid = report.get("run_id", d.name)
            if rid in seen_ids: continue    # output/ version already listed
            seen_ids.add(rid)
            site = _site_key(report.get("url", ""))
            runs.append({
                "run_id":       rid,
                "label":        _run_label(report, d.stat().st_mtime),
                "site":         site,
                "site_name":    SITE_NAMES.get(site, "Custom"),
                "total_issues": found,
                "total_fixed":  report.get("total_fixed", 0),
                "rounds_used":  report.get("rounds_used", 0),
                "featured":     featured.get(site) == rid,
                "_url_prefix":  url_prefix,   # internal — stripped before return
            })

    # Strip internal key
    for r in runs:
        r.pop("_url_prefix", None)
    return {"runs": runs}


@app.get("/api/run/{run_id}/diff")
async def get_diff(run_id: str):
    """
    Return a unified diff between the original page HTML and the final fixed.html.
    Works for both output/ and sample_runs/ runs.
    """
    import difflib, re
    run_dir = _find_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="Run not found")
    fixed_path  = run_dir / "fixed.html"
    report_path = run_dir / "loop_report.json"
    if not fixed_path.exists():
        return {"has_diff": False, "hunks": []}
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="loop_report.json not found for this run")

    report     = json.loads(report_path.read_text())
    fixed_html = fixed_path.read_text(encoding="utf-8")

    original_path = run_dir / "original.html"
    if not original_path.is_file():
        site = _site_key(report.get("url", ""))
        original_path = settings.DEMO_DIR / f"{site}.html"
    if not original_path.is_file():
        raise HTTPException(status_code=422, detail="This run has no saved original HTML.")
    original_html = original_path.read_text(encoding="utf-8")

    # Build unified diff
    orig_lines  = original_html.splitlines(keepends=True)
    fixed_lines = fixed_html.splitlines(keepends=True)
    raw_diff    = list(difflib.unified_diff(orig_lines, fixed_lines,
                                             fromfile="original.html",
                                             tofile="fixed.html",
                                             n=3))

    # Parse into hunks
    hunks = []
    current = None
    for line in raw_diff:
        if line.startswith("@@"):
            if current: hunks.append(current)
            current = {"header": line.rstrip(), "lines": [], "issue_id": None, "issue_desc": None}
        elif current is not None:
            current["lines"].append(line.rstrip("\n"))
    if current: hunks.append(current)

    # Map hunks to issues by keyword overlap
    issues = report.get("per_issue", [])
    analysis_issues = report.get("analysis_issues", [])
    # Build a combined list of (id, keywords) for matching
    all_issue_meta = {}
    for iss in issues:
        words = set(re.findall(r"\w+", (iss.get("description","") + " " + iss.get("element_description","")).lower()))
        all_issue_meta[iss["id"]] = {"desc": iss.get("description",""), "words": words}
    # Also add selector info from analysis_issues
    for ai in analysis_issues:
        if ai["id"] in all_issue_meta:
            all_issue_meta[ai["id"]]["words"].update(
                set(re.findall(r"\w+", ai.get("element_description","").lower()))
            )

    def hunk_to_issue(hunk_lines):
        changed = " ".join(l[1:] for l in hunk_lines if l.startswith(("+","-")))
        changed_words = set(re.findall(r"\w+", changed.lower()))
        best_id, best_score = None, 0
        for iid, meta in all_issue_meta.items():
            score = len(meta["words"] & changed_words)
            if score > best_score:
                best_score, best_id = score, iid
        return best_id if best_score >= 2 else None

    for hunk in hunks:
        iid = hunk_to_issue(hunk["lines"])
        if iid and iid in all_issue_meta:
            hunk["issue_id"]   = iid
            hunk["issue_desc"] = all_issue_meta[iid]["desc"]
        else:
            hunk["issue_id"]   = None
            hunk["issue_desc"] = None

    # Summary stats
    total_additions = sum(1 for h in hunks for l in h["lines"] if l.startswith("+") and not l.startswith("+++"))
    total_deletions = sum(1 for h in hunks for l in h["lines"] if l.startswith("-") and not l.startswith("---"))
    # Rough "rules changed" — count selector-like lines touched
    rules_changed = len(set(
        re.search(r"[.#\w-]+\s*\{", l[1:]).group(0)
        for h in hunks for l in h["lines"]
        if l.startswith(("+","-")) and re.search(r"[.#\w-]+\s*\{", l[1:])
    ))

    return {
        "run_id":          run_id,
        "hunks":           hunks,
        "total_hunks":     len(hunks),
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "rules_changed":   rules_changed,
        "has_diff":        len(hunks) > 0,
    }


@app.get("/api/run/{run_id}")
async def get_run(run_id: str):
    """
    Return the loop_report.json for a saved run.
    Checks output/ first, then sample_runs/.
    Rewrites /output/<run_id>/... image paths to /sample-runs/<run_id>/...
    when the run lives in sample_runs/ so the frontend gets servable URLs.
    """
    run_dir = _find_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="Run not found")
    report_path = run_dir / "loop_report.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    report = json.loads(report_path.read_text())

    # If the run came from sample_runs/, its stored paths say /output/<run_id>/...
    # but the files are served at /sample-runs/<run_id>/... — rewrite them.
    is_sample = str(run_dir).startswith(str(SAMPLE_RUNS_DIR))
    if is_sample:
        report_str = json.dumps(report)
        report_str = report_str.replace(
            f"/output/{run_id}/", f"/sample-runs/{run_id}/"
        )
        report = json.loads(report_str)

    return report


class ReplayRequest(BaseModel):
    demo:    str
    run_id:  str

@app.post("/api/replay")
async def save_replay(req: ReplayRequest):
    """Mark a run_id as the featured replay for a demo site."""
    run = _find_run_dir(req.run_id)
    if run is None or not (run / "loop_report.json").is_file():
        raise HTTPException(status_code=404, detail="Run not found")
    if req.demo not in (*SITE_NAMES, "custom"):
        raise HTTPException(status_code=422, detail="Unknown demo")
    meta = _load_meta()
    meta.setdefault("featured", {})[req.demo] = req.run_id
    _save_meta(meta)
    return {"ok": True, "featured": meta["featured"]}

@app.get("/api/replay")
async def get_replays():
    """Get all demo → run_id featured mappings."""
    return _load_meta().get("featured", {})

@app.post("/api/run/{run_id}/hide")
async def hide_run(run_id: str):
    """Hide a run from the saved runs list."""
    if _find_run_dir(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    meta = _load_meta()
    meta.setdefault("hidden", [])
    if run_id not in meta["hidden"]:
        meta["hidden"].append(run_id)
    _save_meta(meta)
    return {"ok": True}
