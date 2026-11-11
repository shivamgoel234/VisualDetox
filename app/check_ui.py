"""Run DOM checks + screenshots on the UI home, progress and result views."""
import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright
from app.dom_checks import run_dom_checks

OUT = Path("output/ui_screenshots")

async def screenshot(page, name):
    OUT.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
    print(f"  screenshot → {name}.png")

async def main():
    # ── DOM checks on home page at 1280 and 390 ──────────────────────────────
    for vp in ["desktop", "mobile"]:
        r = await run_dom_checks("http://127.0.0.1:8000/", vp)
        label = "desktop (1280)" if vp == "desktop" else "mobile (390)"
        print(f"\nHome {label}: {len(r['findings'])} findings, {len(r['ignored'])} ignored")
        for f in r["findings"]:
            print(f"  [{f['type']}] {f['selector']}: {f['description'][:70]}")

    async with async_playwright() as p:
        # ── Home screenshot ──────────────────────────────────────────────────
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        await page.wait_for_timeout(1000)
        await screenshot(page, "home_1280")

        # Mobile home
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.reload(wait_until="networkidle")
        await page.wait_for_timeout(800)
        await screenshot(page, "home_390")

        # ── Progress screenshot (trigger replay) ─────────────────────────────
        await page.set_viewport_size({"width": 1280, "height": 800})
        await page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        await page.click("#show-runs-btn")
        await page.wait_for_timeout(500)
        run = page.locator(".run-item").first
        if await run.count():
            await run.click()
            await page.wait_for_timeout(1800)   # mid-animation
            await screenshot(page, "progress")

            # ── Result screenshot ────────────────────────────────────────────
            await page.wait_for_timeout(6000)
            await screenshot(page, "result")

            # ── DOM check on result page ────────────────────────────────────
            for vp_name, w in [("desktop", 1280), ("mobile", 390)]:
                await page.set_viewport_size({"width": w, "height": 844})
                findings = await page.evaluate("""() => {
                    const issues = [];
                    document.querySelectorAll('.issue-text,.result-summary h1,.hero-heading').forEach(el => {
                        const s = window.getComputedStyle(el);
                        const c = s.color;
                        // quick check for near-black
                        const ok = c.includes('22, 22') || c.includes('16, 16') || c.includes('rgb(0') || c.includes('rgb(255');
                        if (!ok) issues.push({el: el.tagName + '.' + el.className, color: c});
                    });
                    return issues;
                }""")
                if findings:
                    print(f"\n  Color issues on result page ({vp_name}):")
                    for f in findings:
                        print(f"    {f['el']}: {f['color']}")
                else:
                    print(f"\nResult page ({vp_name}): colors OK")

        # ── Error screenshot ─────────────────────────────────────────────────
        await page.evaluate("document.querySelectorAll('.view').forEach(v=>v.hidden=true); document.getElementById('error-view').hidden=false; document.getElementById('error-msg').textContent='Could not reach the page. Check the URL and try again.';")
        await page.set_viewport_size({"width": 1280, "height": 800})
        await screenshot(page, "error")

        await browser.close()

    print(f"\nScreenshots saved to {OUT.resolve()}")

asyncio.run(main())
