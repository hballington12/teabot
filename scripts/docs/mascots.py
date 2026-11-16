# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=11"]
# ///
"""The home page's three mascots, from the full-size art in brand/: uv run scripts/docs/mascots.py

Each is scaled to 256 px, enough for the panels on high-density screens, and saved as an optimised PNG, so the home
page loads a few hundred kilobytes, not the originals' megabytes.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SIZE = 256
MASCOTS = {
    "teabot_small.png": "guild-admins.png",
    "teabot_medium.png": "self-hosters.png",
    "teabot_large.png": "plugin-developers.png",
}

out = ROOT / "docs/assets/mascots"
out.mkdir(parents=True, exist_ok=True)
for source, target in MASCOTS.items():
    with Image.open(ROOT / "brand" / source) as art:
        small = art.convert("RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
        small.save(out / target, optimize=True)
    print(f"{target}: {(out / target).stat().st_size // 1024} KB")
