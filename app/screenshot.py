"""Capture browser screenshots and measurements from the same page state."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import Browser, Page, Playwright, async_playwright

from app.config import settings
from app.dom_checks import measure_page

logger = logging.getLogger(__name__)

VIEWPORTS = {
    "desktop": {"width": 1280, "height": 800},
    "mobile": {"width": 390, "height": 844},
}


class BrowserSession:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def get_browser(self) -> Browser:
        async with self._lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            if self._browser is None or not self._browser.is_connected():
                self._browser = await self._playwright.chromium.launch(channel=settings.BROWSER_CHANNEL)
            return self._browser

    async def close(self) -> None:
        try:
            if self._browser and self._browser.is_connected():
                await asyncio.wait_for(self._browser.close(), timeout=8)
        except TimeoutError:
            logger.warning("Chromium did not close before the shutdown deadline")
        finally:
            if self._playwright:
                try:
                    await asyncio.wait_for(self._playwright.stop(), timeout=8)
                except TimeoutError:
                    logger.warning("Playwright did not stop before the shutdown deadline")


_server_session: BrowserSession | None = None


@asynccontextmanager
async def browser_lifespan(_app):
    global _server_session
    session = BrowserSession()
    _server_session = session
    try:
        yield
    finally:
        _server_session = None
        await session.close()


@asynccontextmanager
async def _capture_browser():
    session = _server_session or BrowserSession()
    try:
        yield await session.get_browser()
    finally:
        if session is not _server_session:
            await session.close()


async def load_page(page: Page, url: str) -> None:
    response = await page.goto(url, wait_until="load", timeout=25_000)
    if response and not response.ok:
        raise RuntimeError(f"Page returned HTTP {response.status}.")
    await page.evaluate("() => Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 1500))])")


async def _capture(browser: Browser, url: str, viewport: str, path: Path, measure: bool) -> dict:
    context = await browser.new_context(viewport=VIEWPORTS[viewport], device_scale_factor=1)
    try:
        page = await context.new_page()
        await load_page(page, url)
        await page.screenshot(path=str(path), animations="disabled", timeout=10_000)
        return await measure_page(page) if measure else {}
    finally:
        await context.close()


async def capture_viewports(
    url: str, run_id: str, prefix: str = "before", *,
    viewports: tuple[str, ...] = ("desktop", "mobile"), measure: bool = True,
) -> tuple[dict[str, Path], dict[str, dict]]:
    directory = settings.OUTPUT_DIR / run_id
    directory.mkdir(parents=True, exist_ok=True)
    paths = {viewport: directory / f"{prefix}_{viewport}.png" for viewport in viewports}
    async with _capture_browser() as browser:
        try:
            async with asyncio.TaskGroup() as captures:
                tasks = {
                    viewport: captures.create_task(_capture(browser, url, viewport, path, measure))
                    for viewport, path in paths.items()
                }
        except ExceptionGroup as exc:
            raise exc.exceptions[0] from exc
    return paths, {viewport: task.result() for viewport, task in tasks.items()}


async def screenshot(url: str, run_id: str, viewport_name: str = "desktop", prefix: str = "before") -> Path:
    paths, _ = await capture_viewports(url, run_id, prefix, viewports=(viewport_name,), measure=False)
    return paths[viewport_name]


async def screenshot_both(url: str, run_id: str, prefix: str = "before") -> dict[str, Path]:
    paths, _ = await capture_viewports(url, run_id, prefix, measure=False)
    return paths
