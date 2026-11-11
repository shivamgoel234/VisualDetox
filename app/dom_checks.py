"""
app/dom_checks.py
─────────────────
Cheap DOM-level checks run inside Playwright before calling any AI model.
These are fast, deterministic, and free — they feed into the vision model
as additional context so Spark can confirm / expand on them.

Checks performed
────────────────
  1. horizontal_overflow  – elements wider than the viewport
  2. outside_viewport     – elements partially outside the visible area
  3. low_contrast         – text whose contrast ratio < 4.5 (WCAG AA)
  4. overlapping_text     – two text nodes whose bounding boxes intersect

Each finding is a dict:
  {
    type:        str,          # one of the four check names above
    selector:    str,          # CSS selector (best-effort)
    description: str,          # human-readable summary
    bbox:        {x, y, w, h}, # bounding box in CSS pixels
    extra:       dict          # check-specific data (e.g. contrast_ratio)
  }

Public API
──────────
  run_dom_checks(url, viewport_name) -> list[dict]
"""

from playwright.async_api import Page, async_playwright

from app.config import settings

_DOM_CHECK_JS = """
() => {
  const findings = [];
  const ignored  = [];          // decorative elements filtered out
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  // ── helper: build a best-effort CSS selector for a DOM element ──────────
  function selector(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    let path = el.tagName.toLowerCase();
    if (el.className && typeof el.className === 'string') {
      const cls = el.className.trim().split(/\\s+/).slice(0, 2).join('.');
      if (cls) path += '.' + cls;
    }
    return path;
  }

  // ── helper: decorative-element test ──────────────────────────────────────
  // Returns a reason string if the element should be skipped, else null.
  function decorativeReason(el) {
    // aria-hidden
    if (el.getAttribute('aria-hidden') === 'true') return 'aria-hidden';
    // role=presentation or role=none
    const role = el.getAttribute('role');
    if (role === 'presentation' || role === 'none') return 'role=presentation';
    const st = window.getComputedStyle(el);
    // pointer-events:none (not interactive)
    if (st.pointerEvents === 'none') return 'pointer-events:none';
    // visibility:hidden or display:none
    if (st.visibility === 'hidden' || st.display === 'none') return 'invisible';
    // position:absolute/fixed with no visible text content
    if ((st.position === 'absolute' || st.position === 'fixed')) {
      const txt = (el.innerText || '').trim();
      if (!txt) return 'position:absolute, no text';
    }
    return null;
  }

  // ── helper: relative luminance per WCAG 2.1 ─────────────────────────────
  function luminance(r, g, b) {
    const srgb = [r, g, b].map(c => {
      c /= 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * srgb[0] + 0.7152 * srgb[1] + 0.0722 * srgb[2];
  }
  function contrastRatio(hex1, hex2) {
    function parse(hex) {
      const c = hex.replace(/^#/, '');
      if (c.length === 3) {
        return [parseInt(c[0]+c[0],16), parseInt(c[1]+c[1],16), parseInt(c[2]+c[2],16)];
      }
      return [parseInt(c.slice(0,2),16), parseInt(c.slice(2,4),16), parseInt(c.slice(4,6),16)];
    }
    // If we can't parse (e.g. rgba()), bail out
    try {
      const [r1,g1,b1] = parse(hex1);
      const [r2,g2,b2] = parse(hex2);
      const L1 = luminance(r1,g1,b1);
      const L2 = luminance(r2,g2,b2);
      const bright = Math.max(L1,L2);
      const dark   = Math.min(L1,L2);
      return (bright + 0.05) / (dark + 0.05);
    } catch(e) { return null; }
  }
  // Convert any CSS color string to #rrggbb using a temporary canvas element
  function toHex(cssColor) {
    try {
      const c = document.createElement('canvas');
      c.width = c.height = 1;
      const ctx = c.getContext('2d');
      ctx.fillStyle = cssColor;
      ctx.fillRect(0,0,1,1);
      const d = ctx.getImageData(0,0,1,1).data;
      return '#' + [d[0],d[1],d[2]].map(v => v.toString(16).padStart(2,'0')).join('');
    } catch(e) { return null; }
  }

  // ── CHECK 1: horizontal overflow ─────────────────────────────────────────
  document.querySelectorAll('*').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;  // invisible
    const dec = decorativeReason(el);
    if (r.right > vw + 2) {  // 2px tolerance for sub-pixel rounding
      const overflow_px = Math.round(r.right - vw);
      if (dec) {
        ignored.push({ type: 'horizontal_overflow', selector: selector(el),
                       ignore_reason: dec, measured_value: overflow_px });
        return;
      }
      findings.push({
        type: 'horizontal_overflow',
        selector: selector(el),
        description: `Element extends ${overflow_px}px beyond the right edge of the ${vw}px viewport`,
        bbox: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
        extra: { overflow_px, measured_value: overflow_px, target_value: 0,
                 unit: 'px', measurement: `${overflow_px}px overflow (target: 0px)` }
      });
    }
  });

  // ── CHECK 2: elements outside the visible viewport ───────────────────────
  // ONLY flags genuine layout bugs:
  //   • Horizontally clipped (left or right edge beyond viewport)
  //   • Scrolled above the top (r.bottom < 0) — almost never a real layout
  //   • Fixed/absolute/sticky positioned elements that are still off-screen
  //     vertically (they cannot scroll into view, so they truly ARE hidden)
  // Deliberately excluded: elements that are BELOW the fold (r.top > vh)
  // on a normal scrollable page — those require scrolling, not fixing.
  document.querySelectorAll('*').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;

    const st = window.getComputedStyle(el);
    const pos = st.position;
    const isFixed = pos === 'fixed' || pos === 'sticky';
    const isAbsolute = pos === 'absolute';

    // Horizontal clip — always a bug
    const hClipped = r.right < -2 || r.left > vw + 2;
    // Off the top — always a bug
    const offTop = r.bottom < 0;
    // Fixed/absolute that is also off-screen vertically — cannot scroll to it
    const fixedOffScreen = (isFixed || isAbsolute) && r.top > vh;

    if (!hClipped && !offTop && !fixedOffScreen) return;

    const text = el.innerText ? el.innerText.trim() : '';
    if (!text && el.children.length === 0) return;
    const dec = decorativeReason(el);
    if (dec) {
      ignored.push({ type: 'outside_viewport', selector: selector(el), ignore_reason: dec });
      return;
    }

    // Describe whether it's horizontal, vertical, or both
    let desc = '';
    if (hClipped) {
      const side = r.left > vw + 2 ? 'right' : 'left';
      desc = `Element is clipped off the ${side} edge of the viewport`;
    } else if (offTop) {
      desc = `Element is scrolled above the top of the viewport`;
    } else {
      desc = `Fixed/absolute element is outside the visible viewport`;
    }

    findings.push({
      type: 'outside_viewport',
      selector: selector(el),
      description: desc,
      bbox: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
      extra: { measured_value: 1, target_value: 0, unit: 'bool',
               measurement: 'outside viewport (target: inside)',
               clipped_side: hClipped ? (r.left > vw + 2 ? 'right' : 'left') : 'vertical' }
    });
  });

  // ── CHECK 3: low contrast text ────────────────────────────────────────────
  const textTags = ['P','H1','H2','H3','H4','H5','H6','SPAN','A','BUTTON','LI','TD','TH','LABEL'];

  // Walk up the DOM to find the first ancestor with a non-transparent background.
  function effectiveBgHex(el) {
    let node = el;
    while (node && node !== document.documentElement) {
      const bg = window.getComputedStyle(node).backgroundColor;
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
        return toHex(bg);
      }
      node = node.parentElement;
    }
    return '#ffffff';
  }

  document.querySelectorAll(textTags.join(',')).forEach(el => {
    const text = el.innerText ? el.innerText.trim() : '';
    if (!text) return;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    const dec = decorativeReason(el);
    const style = window.getComputedStyle(el);
    const fg = toHex(style.color);
    const bg = effectiveBgHex(el);
    if (!fg || !bg) return;
    const cr = contrastRatio(fg, bg);
    if (cr !== null && cr < 4.5) {
      if (dec) {
        ignored.push({ type: 'low_contrast', selector: selector(el),
                       ignore_reason: dec, measured_value: Math.round(cr * 100) / 100 });
        return;
      }
      const crRounded = Math.round(cr * 100) / 100;
      findings.push({
        type: 'low_contrast',
        selector: selector(el),
        description: `Text contrast ratio ${cr.toFixed(2)}:1 is below WCAG AA minimum of 4.5:1`,
        bbox: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
        extra: { contrast_ratio: crRounded, fg_color: fg, bg_color: bg,
                 measured_value: crRounded, target_value: 4.5,
                 unit: ':1 ratio', measurement: `${crRounded}:1 (target: ≥4.5:1)` }
      });
    }
  });

  // ── CHECK 4: overlapping text boxes ──────────────────────────────────────
  const textEls = Array.from(document.querySelectorAll(textTags.join(',')))
    .filter(el => {
      const t = el.innerText ? el.innerText.trim() : '';
      const r = el.getBoundingClientRect();
      return t.length > 0 && r.width > 0 && r.height > 0 && !decorativeReason(el);
    });

  const sample = textEls.slice(0, 60);
  for (let i = 0; i < sample.length; i++) {
    for (let j = i + 1; j < sample.length; j++) {
      const a = sample[i].getBoundingClientRect();
      const b = sample[j].getBoundingClientRect();
      if (sample[i].contains(sample[j]) || sample[j].contains(sample[i])) continue;
      const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (overlapX > 4 && overlapY > 4) {
        const ov = Math.round(overlapX * overlapY);
        findings.push({
          type: 'overlapping_text',
          selector: selector(sample[i]) + ' / ' + selector(sample[j]),
          description: `Text elements overlap by ${Math.round(overlapX)}×${Math.round(overlapY)}px`,
          bbox: {
            x: Math.round(Math.min(a.left, b.left)),
            y: Math.round(Math.min(a.top, b.top)),
            w: Math.round(Math.max(a.right, b.right) - Math.min(a.left, b.left)),
            h: Math.round(Math.max(a.bottom, b.bottom) - Math.min(a.top, b.top)),
          },
          extra: { overlap_px: { x: Math.round(overlapX), y: Math.round(overlapY) },
                   measured_value: ov, target_value: 0,
                   unit: 'px²', measurement: `${Math.round(overlapX)}×${Math.round(overlapY)}px overlap (target: 0)` }
        });
      }
    }
  }

  return { findings, ignored };
}
"""


async def measure_page(page: Page) -> dict:
    result = await page.evaluate(_DOM_CHECK_JS)
    # The JS now returns {"findings": [...], "ignored": [...]}
    raw_findings = result.get("findings", [])
    raw_ignored  = result.get("ignored",  [])

    # Deduplicate findings: keep only the first per (type, selector) pair
    seen = set()
    deduped = []
    for f in raw_findings:
        key = (f["type"], f["selector"])
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    # Deduplicate ignored the same way
    seen_ig = set()
    deduped_ig = []
    for ig in raw_ignored:
        key = (ig.get("type"), ig.get("selector"))
        if key not in seen_ig:
            seen_ig.add(key)
            deduped_ig.append(ig)

    return {"findings": deduped, "ignored": deduped_ig}


async def run_dom_checks(url: str, viewport_name: str = "desktop") -> dict:
    from app.screenshot import VIEWPORTS, load_page

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=settings.BROWSER_CHANNEL)
        try:
            page = await browser.new_page(viewport=VIEWPORTS[viewport_name], device_scale_factor=1)
            await load_page(page, url)
            return await measure_page(page)
        finally:
            await browser.close()
