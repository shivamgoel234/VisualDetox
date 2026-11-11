"""Capture a page and collect issues for the repair loop."""

import asyncio
import json
import re
import uuid
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from app.annotate import annotate_issue
from app.config import settings
from app.issue_merge import merge_issues
from app.models import ModelError, find_issues
from app.screenshot import capture_viewports

RUN_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}")
DEMO_PATH = re.compile(r"/demo-sites/demo[1-4]\.html")


class AuditInputError(ValueError):
    """A URL or run ID the API cannot accept."""


def demo_file(url: str) -> Path | None:
    parsed = urlsplit(url)
    if (
        parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.port == settings.PORT
        and DEMO_PATH.fullmatch(parsed.path)
    ):
        return settings.DEMO_DIR / Path(parsed.path).name
    return None


def validate_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError as exc:
        raise AuditInputError("Enter a valid HTTP or HTTPS URL.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
        raise AuditInputError("Enter an HTTP or HTTPS page URL without credentials.")
    if settings.MOCK_MODE and not demo_file(url):
        raise AuditInputError("Fixture mode supports the bundled demo pages. Select a demo or configure Gemini.")


async def analyze(url: str, run_id: str | None = None, on_progress=None) -> dict:
    validate_url(url)
    if not settings.MOCK_MODE and not settings.GEMINI_API_KEY:
        raise ModelError("Set GEMINI_API_KEY in .env to run a live audit.")
    run_id = run_id or uuid.uuid4().hex[:8]
    if not RUN_ID.fullmatch(run_id):
        raise AuditInputError("Run ID must use letters, digits, underscores or hyphens.")
    try:
        (settings.OUTPUT_DIR / run_id).mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise AuditInputError("This run ID already exists. Start a new audit.") from exc

    started = monotonic()
    if on_progress:
        await on_progress("screenshotting", "started")
    screenshots, measurements = await capture_viewports(url, run_id)
    findings = [
        {**finding, "viewport": viewport}
        for viewport, checks in measurements.items()
        for finding in checks["findings"]
    ]
    ignored = [item for checks in measurements.values() for item in checks["ignored"]]
    if on_progress:
        await on_progress("screenshotting", "done", elapsed=round(monotonic() - started, 1))
        await on_progress("dom_checks", "done", count=len(findings))
        await on_progress("finding_issues", "started")

    started = monotonic()
    issues = [] if settings.MOCK_MODE else await asyncio.to_thread(
        find_issues, screenshots["desktop"].read_bytes(), findings,
        mobile_png=screenshots["mobile"].read_bytes(),
    )
    if on_progress:
        await on_progress("finding_issues", "done", elapsed=round(monotonic() - started, 1), count=len(issues))
        await on_progress("outlining", "started")
    started = monotonic()

    # Match against the same merged issues the fixer will use.
    annotated = merge_issues(issues, findings)
    for issue in annotated:
        viewport = issue.get("dom_viewport") or issue["viewport"]
        box = issue.get("dom_bbox")
        if not box or viewport not in screenshots:
            issue["annotation"] = {"path": "", "method": "none", "boxes": []}
            continue
        annotation = annotate_issue(
            screenshots[viewport], "", box, issue["id"], issue["severity"]
        )
        issue["annotation"] = {**annotation, "path": str(annotation["path"])}

    report = {
        "run_id": run_id,
        "url": url,
        "mock_mode": settings.MOCK_MODE,
        "screenshots": {viewport: str(path) for viewport, path in screenshots.items()},
        "dom_findings": findings,
        "dom_ignored": ignored,
        "issues": annotated,
    }
    (settings.OUTPUT_DIR / run_id / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    if on_progress:
        await on_progress("outlining", "done", elapsed=round(monotonic() - started, 1))
    return report
