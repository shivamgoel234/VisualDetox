"""
Resize screenshots for docs/img/ — max 1600px wide, optimised PNG.
Each file must come out under 400 KB.
"""
from pathlib import Path
from PIL import Image
import io

OUT = Path("docs/img")
OUT.mkdir(parents=True, exist_ok=True)

IMAGES = {
    # (source_path, dest_name)
    "output/ef46d748/before_mobile.png":     "demo4_mobile_before.png",
    "output/a4cffef2/after_r1_mobile.png":   "demo4_mobile_after.png",
    "output/b486c55b/before_desktop.png":    "demo1_desktop_before.png",
    "output/b486c55b/after_r2_desktop.png":  "demo1_desktop_after.png",
    # UI screenshots captured earlier
    "output/ui_screenshots/home_1440.png":   "ui_home.png",
    "output/ui_screenshots/result.png":      "ui_result.png",
    "output/ef46d748/ui_changes_tab.png":    "ui_changes.png",
    "output/ef46d748/progress_1440.png":     "ui_progress.png",
}

MAX_W = 1600
MAX_KB = 400

for src_str, dest_name in IMAGES.items():
    src = Path(src_str)
    if not src.exists():
        # Try ui_screenshots path variations
        alt = Path("output/cp1") / src.name
        if alt.exists():
            src = alt
        else:
            print(f"  SKIP (not found): {src_str}")
            continue

    dest = OUT / dest_name
    img = Image.open(src).convert("RGB")

    # Resize if wider than MAX_W
    if img.width > MAX_W:
        ratio = MAX_W / img.width
        img = img.resize((MAX_W, int(img.height * ratio)), Image.LANCZOS)

    # Save with optimise; try progressively higher compression if over limit
    for quality in [85, 75, 65, 55]:
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        size_kb = len(buf.getvalue()) / 1024
        if size_kb <= MAX_KB:
            break
        # PNG doesn't have quality; try JPEG instead if still too big
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        size_kb = len(buf.getvalue()) / 1024
        if size_kb <= MAX_KB:
            dest = dest.with_suffix(".jpg")
            break

    dest.write_bytes(buf.getvalue())
    print(f"  {dest.name:<35} {size_kb:.0f} KB  ({img.width}×{img.height})")

print("\nDone.")
