# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=11"]
# ///
"""The site's and README's images, from the full-size art in brand/: uv run scripts/docs/brand.py

- The home page's three mascots, 256 px, in docs/assets/mascots/.
- Teabot's icon, the large mascot cropped to the art and squared: 512 px for the README (brand/teabot.png), 256 px
  for the docs' logo (docs/assets/teabot.png), and 64 px for the browser tab (docs/assets/favicon.png).

Each is saved as an optimised PNG, so pages load kilobytes, not the originals' megabytes.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "brand"
MASCOTS = {
    "teabot_small.png": "guild-admins.png",
    "teabot_medium.png": "self-hosters.png",
    "teabot_large.png": "plugin-developers.png",
}
ICON = "teabot_large.png"
ICONS = {
    BRAND / "teabot.png": 512,
    ROOT / "docs/assets/teabot.png": 256,
    ROOT / "docs/assets/favicon.png": 64,
}


def save(art: Image.Image, size: int, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    art.resize((size, size), Image.Resampling.LANCZOS).save(target, optimize=True)
    print(f"{target.relative_to(ROOT)}: {size} px, {target.stat().st_size // 1024} KB")


def squared(art: Image.Image, margin: float = 0.03) -> Image.Image:
    """The art cropped to what it draws, centred on a square transparent canvas with a small margin."""
    box = art.getchannel("A").getbbox() or (0, 0, *art.size)
    drawn = art.crop(box)
    side = round(max(drawn.size) * (1 + 2 * margin))
    canvas = Image.new("RGBA", (side, side))
    canvas.paste(drawn, ((side - drawn.width) // 2, (side - drawn.height) // 2))
    return canvas


for source, target in MASCOTS.items():
    with Image.open(BRAND / source) as art:
        save(art.convert("RGBA"), 256, ROOT / "docs/assets/mascots" / target)

with Image.open(BRAND / ICON) as art:
    icon = squared(art.convert("RGBA"))
for target, size in ICONS.items():
    save(icon, size, target)
