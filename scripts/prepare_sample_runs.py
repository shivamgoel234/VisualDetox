"""
Copy the minimal set of files needed for replay + Changes tab into sample_runs/.

For each featured run we need:
  loop_report.json    — the full report the UI replays
  fixed.html          — needed by the Changes tab diff endpoint
  before_desktop.png, before_mobile.png
  after_r*_desktop.png, after_r*_mobile.png  (all rounds — UI picks final)
  annotated_issue-*.png (overlays shown in the issue ledger on click)

We do NOT copy:
  report.json, fix_report.json — internal pipeline artefacts, not used by UI
  run_meta.json — will be generated fresh in sample_runs/

The original HTML is fetched live by the diff endpoint (it hits the server URL
stored in loop_report.json["url"]).  No need to copy it.
"""
import json, shutil
from pathlib import Path

FEATURED = {
    "demo1": "b486c55b",
    "demo2": "eef541d9",
    "demo3": "15fe1fa6",
    "demo4": "75afaa44",
}

SRC_ROOT  = Path("output")
DEST_ROOT = Path("sample_runs")
DEST_ROOT.mkdir(exist_ok=True)

KEEP_PATTERNS = [
    "loop_report.json",
    "fixed.html",
    "before_desktop.png",
    "before_mobile.png",
    "after_r",          # prefix: catches after_r1_desktop.png etc.
    "annotated_",       # prefix: overlay images
]

total_bytes = 0
for demo, run_id in FEATURED.items():
    src_dir  = SRC_ROOT / run_id
    dest_dir = DEST_ROOT / run_id
    dest_dir.mkdir(exist_ok=True)

    run_bytes = 0
    for f in sorted(src_dir.iterdir()):
        keep = any(
            f.name == p or f.name.startswith(p)
            for p in KEEP_PATTERNS
        )
        if keep:
            shutil.copy2(f, dest_dir / f.name)
            run_bytes += f.stat().st_size
            print(f"  {demo}/{run_id}/{f.name}  ({f.stat().st_size//1024} KB)")
    total_bytes += run_bytes
    print(f"  → {demo} subtotal: {run_bytes//1024} KB\n")

# Write the featured mapping so the server can find these runs
meta = {"featured": {k: v for k, v in FEATURED.items()}, "hidden": []}
(DEST_ROOT / "run_meta.json").write_text(json.dumps(meta, indent=2))
print(f"sample_runs/run_meta.json written")
print(f"\nTotal sample_runs: {total_bytes/1024/1024:.2f} MB")
