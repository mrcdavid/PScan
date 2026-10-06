"""Regenerate the PScan app icons. Run with the PC venv: ..\\..\\pc\\.venv\\Scripts\\python make_icons.py"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "pc"))

from pscan_server.icon import draw_icon  # noqa: E402

for size in (48, 72, 96, 144, 192):
    draw_icon(size).save(HERE / f"pscan-square-{size}.png")
    # Round launcher icon: same artwork on a circle.
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    circle = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    circle.paste(draw_icon(size, padding=0.06), (0, 0), mask)
    circle.save(HERE / f"pscan-round-{size}.png")

for size in (320, 480, 640, 960, 1280):
    # Larger square icons (used for the Android splash screen).
    draw_icon(size).save(HERE / f"pscan-square-{size}.png")

for size in (108, 162, 216, 324, 432):
    # Adaptive icon: full-bleed gradient (the launcher applies its own mask) with the
    # artwork inside the central safe zone.
    draw_icon(size, padding=0.18, rounded=False).save(HERE / f"pscan-adaptive-{size}.png")

draw_icon(256).save(HERE / "pscan.png")
draw_icon(256).save(HERE / "pscan.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("Icons written to", HERE)
