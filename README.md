# VisualDetox

VisualDetox audits a webpage at desktop and mobile widths. It captures the page, measures layout and contrast defects, proposes a repair to a local HTML copy, and shows which issues passed verification. The comparison, issue ledger, and source diff are available from the same report.

## Run locally

Use Python 3.12 or 3.13. From PowerShell in the project directory:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
Copy-Item .env.example .env
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [VisualDetox locally](http://127.0.0.1:8000). **Open report** displays the bundled Northwind Coffee comparison immediately. Choose one of the four demo pages and submit it to run the browser workflow in fixture mode. Fixture runs apply an archived repair and evaluate it with browser measurements. The original saved reports retain their original verification results.

For live audits, create a [Google AI Studio API key](https://aistudio.google.com/apikey) and set these values in your local .env:

```dotenv
MOCK_MODE=false
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.1-flash-lite
```

Keep PORT in .env aligned with Uvicorn. With an installed Microsoft Edge, BROWSER_CHANNEL=msedge can be used in place of downloading Playwright Chromium.

## Provider and cost

SiteSurgeon used Meta Muse Spark 1.3 for issue discovery, HTML repair, and visual verification. Meta lists its standard rates at $1.25 per million input tokens and $4.25 per million output tokens, with $0.15 per million cached input tokens. SAM 3.1 is billed separately at $2.50 per 1,000 images. [Meta Model API pricing](https://dev.meta.ai/products/meta-model-api)

VisualDetox uses Gemini 3.1 Flash-Lite, which accepts screenshots and supports structured text output. Google lists free standard input and output within the free tier. Limits depend on the project and model. A live audit can make several calls across its repair rounds. Google lists free-tier content as eligible for product improvement, so use public pages you are authorized to audit. [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) · [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)

Changing the provider required changing the request and response formats. Gemini handles issue discovery, repair, and verification. Live annotations use browser-measured element boxes. Older reports still display their archived SAM overlays.

## How it works

1. Playwright captures 1280 × 800 and 390 × 844 screenshots. Each screenshot and its DOM measurements come from the same page load. The server reuses Chromium and opens an isolated context for each capture.
2. Gemini receives both screenshots and the browser findings. The audit merges and prioritizes the resulting issue list.
3. Gemini receives the HTML and repair context. The application checks document structure and text retention before accepting the repair.
4. The browser remeasures both views. A live fix requires a passing browser check and a passing visual verdict for each affected viewport. The returned HTML and screenshots come from the same selected round.

FastAPI streams audit progress over server-sent events. The frontend uses plain HTML, CSS, and JavaScript. Gemini responses are cached by model and request. Sample reports are stored in sample_runs, while new reports, screenshots, HTML, and cache files stay local.

The audit measures the initially rendered view. Preview pages sandbox generated HTML and disable scripts, so interactive or JavaScript-dependent pages can render differently in a preview. Run the app locally on loopback for trusted users and audit targets.

## Verification

With the server running in fixture mode:

```powershell
.venv\Scripts\python -m app.e2e_test
.venv\Scripts\python -m app.test_models
```

The end-to-end suite exercises the four demo audits, streaming progress, saved reports, and friendly error responses. Model tests stub Gemini HTTP responses and require zero API credits.

## Attribution

VisualDetox is derived from [SiteSurgeon by suryavashisth2010-ux](https://github.com/suryavashisth2010-ux/SiteSurgeon/tree/a49cdef). The upstream project contributed the FastAPI/Playwright architecture, fixtures, and sample audit evidence. Its README documents its hackathon development and use of Google's Antigravity coding agent.

The VisualDetox changes cover the interface redesign, Gemini integration, browser capture consolidation, verification and artifact fixes, and test updates. The upstream README declares the MIT License. See [LICENSE](LICENSE) and [font notices](static/fonts/LICENSES.md).
