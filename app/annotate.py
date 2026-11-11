"""
app/annotate.py
───────────────
Parse SAM output and draw annotated overlays on screenshots.

Public API
──────────
  parse_sam_boxes(mask_text) -> list[dict]
      Parse the SAM special-token output string into a list of box dicts.
      Each dict: {object_id, x1, y1, x2, y2, w, h}

  draw_overlay(png_path, boxes, fallback_bbox, issue_id, method) -> Path
      Draw a semi-transparent red rectangle overlay on a copy of the PNG.
      Returns the path to the annotated PNG.

  annotate_issue(png_path, mask_text, dom_bbox, issue_id) -> dict
      Top-level helper: tries SAM box first, falls back to dom_bbox.
      Returns {"path": Path, "method": "sam_box" | "dom_box"}

SAM wire format (from https://dev.meta.ai/docs/sam/reading-segmentation):
  <0f>0<|box;x1=353;y1=382;x2=453;y2=427;w=537;h=561|><|mask;...|>
  • Frame marker:  <Nf>
  • Object id:     bare integer before the first <|box
  • Box token:     <|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>
  • Mask token:    <|mask;x=0;y=0;data=H,W,~payload|>  (~ = lossless, ! = one_bit)
  • Mask payload is BASE85 — we skip decoding it for now and just draw the box.
"""

import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── SAM token regex patterns ─────────────────────────────────────────────────
# Match a box token anywhere in the output string
_BOX_RE = re.compile(
    r"<\|box;"
    r"x1=(?P<x1>\d+);"
    r"y1=(?P<y1>\d+);"
    r"x2=(?P<x2>\d+);"
    r"y2=(?P<y2>\d+);"
    r"w=(?P<w>\d+);"
    r"h=(?P<h>\d+)"
    r"(?:;c=[\d.]+)?"   # optional confidence
    r"\|>"
)

# Match the leading object-id before a box (it's the integer right before <|box)
_RECORD_RE = re.compile(r"(?:^|,)\s*(\d+)\s*<\|box")


def parse_sam_boxes(mask_text: str) -> list:
    """
    Parse all box tokens from a SAM output string.

    Returns a list of dicts, each with keys:
      object_id (int), x1, y1, x2, y2, w, h  (all int, source pixels)

    Returns [] if mask_text is empty or contains no box tokens.
    """
    if not mask_text or not mask_text.strip():
        return []

    results = []
    # Find every box token in the string
    for m in _BOX_RE.finditer(mask_text):
        results.append({
            "object_id": None,   # filled below
            "x1": int(m.group("x1")),
            "y1": int(m.group("y1")),
            "x2": int(m.group("x2")),
            "y2": int(m.group("y2")),
            "w":  int(m.group("w")),
            "h":  int(m.group("h")),
        })

    # Try to attach object ids
    for i, m in enumerate(_RECORD_RE.finditer(mask_text)):
        if i < len(results):
            results[i]["object_id"] = int(m.group(1))

    return results


def draw_overlay(
    src_path: Path,
    boxes: list,           # list of {x1, y1, x2, y2, w, h} in SAM source pixels
    fallback_bbox: dict | None,  # {x, y, w, h} in screen pixels (from DOM check)
    issue_id: str,
    method: str,           # "sam_box" | "dom_box"
    label: str = "",
) -> Path:
    """
    Draw a semi-transparent red rectangle on a copy of src_path.

    SAM coordinates are in the source image's own pixel space (w, h in the box
    token).  The saved PNG may have been resized before sending to SAM, so we
    scale the box coordinates back to the PNG's actual dimensions.

    Returns the path of the saved annotated PNG.
    """
    img = Image.open(src_path).convert("RGBA")
    png_w, png_h = img.size

    # Overlay layer (separate so we can use alpha-composite for transparency)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    if method == "sam_box" and boxes:
        for box in boxes:
            # Scale from SAM's source pixels to the actual PNG dimensions
            scale_x = png_w / box["w"] if box["w"] > 0 else 1
            scale_y = png_h / box["h"] if box["h"] > 0 else 1
            x1 = int(box["x1"] * scale_x)
            y1 = int(box["y1"] * scale_y)
            x2 = int(box["x2"] * scale_x)
            y2 = int(box["y2"] * scale_y)

            # Semi-transparent red fill + solid border
            draw.rectangle([x1, y1, x2, y2], fill=(220, 30, 30, 60), outline=(220, 30, 30, 230), width=3)

    elif method == "dom_box" and fallback_bbox:
        x  = fallback_bbox.get("x", 0)
        y  = fallback_bbox.get("y", 0)
        bw = fallback_bbox.get("w", 50)
        bh = fallback_bbox.get("h", 20)
        # DOM bbox is already in CSS px which matches the PNG at device-scale-factor=1
        draw.rectangle([x, y, x + bw, y + bh], fill=(220, 30, 30, 60), outline=(220, 30, 30, 230), width=3)

    # Draw label badge in the top-left of the first box
    badge_text = label or issue_id
    if badge_text:
        try:
            # Try to load a system font; fall back to default if unavailable
            font = ImageFont.truetype("arial.ttf", 14)
        except (OSError, IOError):
            font = ImageFont.load_default()

        # Position: top-left of the bounding area
        if method == "sam_box" and boxes:
            bx = int(boxes[0]["x1"] * (png_w / boxes[0]["w"]))
            by = int(boxes[0]["y1"] * (png_h / boxes[0]["h"]))
        elif fallback_bbox:
            bx, by = fallback_bbox.get("x", 0), fallback_bbox.get("y", 0)
        else:
            bx, by = 4, 4

        # Small red badge
        tw = len(badge_text) * 8 + 6
        draw.rectangle([bx, by - 18, bx + tw, by], fill=(220, 30, 30, 220))
        draw.text((bx + 3, by - 16), badge_text, fill=(255, 255, 255), font=font)

    # Composite the overlay onto the original image
    combined = Image.alpha_composite(img, overlay).convert("RGB")

    # Save next to the source with the issue_id in the filename
    out_path = src_path.parent / f"annotated_{issue_id}_{method}.png"
    combined.save(str(out_path))
    return out_path


def annotate_issue(
    png_path: Path,
    mask_text: str,
    dom_bbox: dict | None,
    issue_id: str,
    label: str = "",
) -> dict:
    """
    Given the SAM output string and a fallback DOM bounding box, draw the
    best available overlay and return which method was used.

    Returns:
      {
        "path":   Path to the annotated PNG,
        "method": "sam_box" | "dom_box",
        "boxes":  list of parsed SAM boxes (may be empty)
      }
    """
    boxes = parse_sam_boxes(mask_text)

    if boxes:
        method = "sam_box"
        print(f"  [annotate] {issue_id}: SAM returned {len(boxes)} box(es) → sam_box overlay")
    elif dom_bbox:
        method = "dom_box"
        print(f"  [annotate] {issue_id}: SAM empty, using DOM bbox → dom_box overlay")
    else:
        # Nothing to draw — return the original image unchanged with a note
        print(f"  [annotate] {issue_id}: no SAM boxes and no DOM bbox — skipping overlay")
        return {"path": png_path, "method": "none", "boxes": []}

    out_path = draw_overlay(
        src_path=png_path,
        boxes=boxes,
        fallback_bbox=dom_bbox,
        issue_id=issue_id,
        method=method,
        label=label,
    )
    return {"path": out_path, "method": method, "boxes": boxes}
