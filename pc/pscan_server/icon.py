"""The PScan icon (maroon→green tile, white page, gold camera lens), drawn with Pillow at any size."""

from __future__ import annotations

from PIL import Image, ImageDraw

MAROON = (141, 20, 54)
GREEN = (0, 86, 63)
GOLD = (255, 182, 28, 255)
WHITE = (255, 255, 255, 255)
LINE = (231, 207, 215, 255)
FOLD = (226, 196, 206, 255)


MID = (106, 24, 56)  # same 3-stop gradient as the app header: maroon, deep maroon, green


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def _gradient(size: int) -> Image.Image:
    """Diagonal maroon → green gradient, like the app header."""
    small = Image.new("RGB", (64, 64))
    px = small.load()
    for y in range(64):
        for x in range(64):
            t = (x + y) / 126
            px[x, y] = _mix(MAROON, MID, t / 0.45) if t < 0.45 else _mix(MID, GREEN, (t - 0.45) / 0.55)
    return small.resize((size, size), Image.Resampling.BICUBIC).convert("RGBA")


def draw_icon(size: int, background: bool = True, padding: float = 0.0, rounded: bool = True) -> Image.Image:
    """Square RGBA icon. ``background=False`` draws only the page; ``rounded=False`` fills the
    whole square (Android adaptive icons, which the launcher masks itself); ``padding``
    shrinks the artwork towards the centre (fraction of ``size`` per side)."""
    scale = 4  # draw big, then downsample for smooth edges
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    if background:
        mask = Image.new("L", (s, s), 0)
        radius = int(s * 0.22) if rounded else 0
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=radius, fill=255)
        img.paste(_gradient(s), (0, 0), mask)
    d = ImageDraw.Draw(img)

    inset = s * padding
    box = s - 2 * inset

    def px(fx: float, fy: float) -> tuple[float, float]:
        return inset + fx * box, inset + fy * box

    # Page with a folded top-right corner.
    left, top, right, bottom, fold = 0.25, 0.16, 0.73, 0.82, 0.14
    page = [px(left, top), px(right - fold, top), px(right, top + fold), px(right, bottom), px(left, bottom)]
    d.polygon(page, fill=WHITE)
    d.polygon([px(right - fold, top), px(right - fold, top + fold), px(right, top + fold)], fill=FOLD)

    # Text lines in maroon tint.
    width = max(1, int(box * 0.04))
    for i, length in enumerate((0.30, 0.36, 0.36, 0.22)):
        y = top + 0.24 + i * 0.095
        d.line([px(left + 0.07, y), px(left + 0.07 + length, y)], fill=LINE, width=width)

    # Gold camera lens with a green centre, bottom-right.
    cx, cy = px(0.71, 0.73)
    r = box * 0.16
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GOLD, outline=WHITE, width=max(1, int(box * 0.035)))
    r2 = r * 0.42
    d.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), fill=(*GREEN, 255))

    return img.resize((size, size), Image.Resampling.LANCZOS)
