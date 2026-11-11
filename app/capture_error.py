"""Capture just the error view with proper CSS load time."""
import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

async def main():
    OUT = Path("output/ui_screenshots"); OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        await page.wait_for_timeout(800)   # let CSS fully apply
        await page.evaluate("""() => {
            document.querySelectorAll('.view').forEach(v => v.hidden = true);
            const ev = document.getElementById('error-view');
            ev.hidden = false;
            document.getElementById('error-msg').textContent = 'Could not reach the page. Check the URL and try again.';
        }""")
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(OUT / "error.png"))
        print("error.png captured")
        await browser.close()

asyncio.run(main())
