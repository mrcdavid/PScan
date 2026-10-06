"""Turn a phone photo of a page into a clean, straight page image.

Pipeline: load (EXIF-upright, size-limited) -> find the page's 4 corners -> perspective
warp -> rotate -> enhance for the chosen mode (color / gray / bw).
"""

from __future__ import annotations

import io
import logging
import re
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

log = logging.getLogger(__name__)

# Phone cameras go up to 200 MP; allow those instead of tripping Pillow's bomb guard.
Image.MAX_IMAGE_PIXELS = 300_000_000

DETECT_SIZE = 1000  # long edge of the copy used for corner detection
MIN_PAGE_AREA = 0.20  # the page must cover at least this much of the photo
OSD_MIN_CONFIDENCE = 5.0  # Tesseract orientation confidence needed to auto-rotate
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ImageDecodeError(ValueError):
    pass


# --------------------------------------------------------------------------- loading


def load_image(data: bytes, max_long_edge: int) -> np.ndarray:
    """Decode photo bytes into an upright BGR array no larger than ``max_long_edge``."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            # Let the JPEG decoder skip detail we would throw away anyway (fast for 50 MP photos).
            im.draft("RGB", (max_long_edge, max_long_edge))
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
            im.thumbnail((max_long_edge, max_long_edge), Image.Resampling.LANCZOS)
            rgb = np.asarray(im)
    except Exception as exc:  # Pillow raises many different types for bad input
        raise ImageDecodeError(f"Not a readable image: {exc}") from exc
    return np.ascontiguousarray(rgb[:, :, ::-1])


def encode_jpeg(img: np.ndarray, quality: int, dpi: float | None = None) -> bytes:
    """Encode a BGR or grayscale array as JPEG, optionally tagging its DPI."""
    if img.ndim == 2:
        pil = Image.fromarray(img, mode="L")
    else:
        pil = Image.fromarray(np.ascontiguousarray(img[:, :, ::-1]), mode="RGB")
    buf = io.BytesIO()
    kwargs = {"quality": quality, "optimize": True}
    if dpi:
        kwargs["dpi"] = (dpi, dpi)
    pil.save(buf, format="JPEG", **kwargs)
    return buf.getvalue()


def decode_jpeg(data: bytes) -> np.ndarray:
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise ImageDecodeError("Stored page image is unreadable")
    return arr


# ----------------------------------------------------------------------- paper sizes

# Paper sizes as (short side, long side) in millimetres.
PAPERS = {
    "A4": (210.0, 297.0),
    "Letter": (215.9, 279.4),
    "Long": (215.9, 330.2),  # "long bond" / Folio, 8.5 x 13 in
    "Legal": (215.9, 355.6),
}
ORIGINAL = "Original"  # keep the page's own shape
PAPER_NAMES = (*PAPERS, ORIGINAL)
SNAP_TOLERANCE = 0.06  # pages this close to the paper's shape are stretched to fit exactly


def fit_to_paper(img: np.ndarray, paper: str) -> np.ndarray:
    """Give the page exactly the paper's proportions (portrait or landscape).

    A photographed sheet of that paper is usually within a few percent of the right shape;
    it's stretched to fit exactly. Anything else (a receipt, an ID, an uncropped photo) is
    centred on a white sheet so nothing is distorted or cut off.
    """
    if paper not in PAPERS:
        return img
    short_mm, long_mm = PAPERS[paper]
    target = long_mm / short_mm
    h, w = img.shape[:2]
    landscape = w > h
    long_px, short_px = max(h, w), min(h, w)
    ratio = long_px / short_px

    if abs(ratio - target) / target <= SNAP_TOLERANCE:
        short_px = round(long_px / target)
        size = (long_px, short_px) if landscape else (short_px, long_px)
        return cv2.resize(img, size, interpolation=cv2.INTER_AREA)

    if ratio > target:  # too long and thin: widen with white
        short_px = round(long_px / target)
    else:  # too wide: lengthen with white
        long_px = round(short_px * target)
    canvas_w, canvas_h = (long_px, short_px) if landscape else (short_px, long_px)
    canvas = np.full((canvas_h, canvas_w, *img.shape[2:]), 255, dtype=img.dtype)
    y, x = (canvas_h - h) // 2, (canvas_w - w) // 2
    canvas[y : y + h, x : x + w] = img
    return canvas


def finalize_page(img: np.ndarray, paper: str) -> tuple[np.ndarray, int]:
    """Fit the page to the paper and choose its DPI so the PDF page is exactly that size.

    JPEG stores DPI as a whole number, so the DPI is rounded first and the pixels are
    resized (by a fraction of a percent) to match it.
    """
    img = fit_to_paper(img, paper)
    dpi = max(1, round(page_dpi(img, paper)))
    if paper in PAPERS:
        short_in, long_in = (mm / 25.4 for mm in PAPERS[paper])
        h, w = img.shape[:2]
        long_px, short_px = round(long_in * dpi), round(short_in * dpi)
        size = (long_px, short_px) if w > h else (short_px, long_px)
        if size != (w, h):
            img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    return img, dpi


def page_dpi(img: np.ndarray, paper: str = ORIGINAL) -> float:
    """DPI that makes the page come out at the paper's real size in the PDF.

    For "Original" the long side becomes 11 inches.
    """
    long_inches = PAPERS[paper][1] / 25.4 if paper in PAPERS else 11.0
    return max(img.shape[:2]) / long_inches


# ------------------------------------------------------------------ corner detection


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Return 4 points ordered top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype=np.float32,
    )


def _is_plausible_page(quad: np.ndarray, image_area: float) -> bool:
    quad = order_corners(quad)
    if len({tuple(p) for p in quad.round(1)}) < 4:
        return False
    if not cv2.isContourConvex(quad.reshape(-1, 1, 2)):
        return False
    area = cv2.contourArea(quad)
    if area < MIN_PAGE_AREA * image_area:
        return False
    # Every corner angle must be roughly square-ish (perspective allows some skew).
    for i in range(4):
        a, b, c = quad[i - 1], quad[i], quad[(i + 1) % 4]
        v1, v2 = a - b, c - b
        cos = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9))
        angle = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
        if not 45.0 <= angle <= 135.0:
            return False
    return True


def _quad_from_contours(contours, image_area: float) -> np.ndarray | None:
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        if cv2.contourArea(contour) < MIN_PAGE_AREA * image_area:
            break
        hull = cv2.convexHull(contour)
        peri = cv2.arcLength(hull, True)
        for eps in (0.02, 0.03, 0.04, 0.06):
            approx = cv2.approxPolyDP(hull, eps * peri, True)
            if len(approx) == 4 and _is_plausible_page(approx, image_area):
                return order_corners(approx)
    return None


def detect_page(img: np.ndarray) -> np.ndarray | None:
    """Find the document's corners in a photo.

    Returns a (4, 2) float32 array in ``img`` pixel coordinates (TL, TR, BR, BL), or
    None when no convincing page outline is found (the caller then keeps the whole photo).
    """
    h, w = img.shape[:2]
    scale = min(1.0, DETECT_SIZE / max(h, w))
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    area = float(sh * sw)

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))

    candidates = []

    # 1) Edge-based: works when the page has a visible border against the background.
    edges = cv2.Canny(gray, 40, 140)
    edges = cv2.dilate(edges, kernel, iterations=1)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates.append(_quad_from_contours(contours, area))

    # 2) Brightness-based: paper is usually lighter than the table it lies on.
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates.append(_quad_from_contours(contours, area))

    for quad in candidates:
        if quad is None:
            continue
        # A "page" that is the whole photo means there's nothing to crop.
        if cv2.contourArea(quad) > 0.97 * area:
            continue
        return (quad / scale).astype(np.float32)
    return None


def true_aspect_ratio(quad: np.ndarray, image_size: tuple[int, int]) -> float | None:
    """Estimate the real width/height ratio of a rectangle photographed in perspective.

    Zhang & He, "Whiteboard scanning and image enhancement" (2007): assumes a pinhole
    camera with square pixels and the principal point at the image centre, which holds
    well for phone cameras. Returns None if the geometry is degenerate.
    """
    tl, tr, br, bl = order_corners(quad).astype(np.float64)
    w, h = image_size
    u0, v0 = w / 2.0, h / 2.0
    m1, m2, m3, m4 = (np.array([p[0] - u0, p[1] - v0, 1.0]) for p in (tl, tr, bl, br))
    try:
        k2 = np.dot(np.cross(m1, m4), m3) / np.dot(np.cross(m2, m4), m3)
        k3 = np.dot(np.cross(m1, m4), m2) / np.dot(np.cross(m3, m4), m2)
    except FloatingPointError:
        return None
    n2 = k2 * m2 - m1
    n3 = k3 * m3 - m1
    denom = n2[2] * n3[2]
    f2 = -(n2[0] * n3[0] + n2[1] * n3[1]) / denom if abs(denom) > 1e-9 else -1.0
    if f2 > 0:
        a_inv = np.diag([1.0 / np.sqrt(f2), 1.0 / np.sqrt(f2), 1.0])
        num = n2 @ a_inv.T @ a_inv @ n2
        den = n3 @ a_inv.T @ a_inv @ n3
    else:  # (nearly) no perspective: plain edge ratio of the rectified vectors
        num = n2[0] ** 2 + n2[1] ** 2
        den = n3[0] ** 2 + n3[1] ** 2
    if den <= 0 or not np.isfinite(num / den):
        return None
    ratio = float(np.sqrt(num / den))
    return ratio if 0.2 <= ratio <= 5.0 else None


def warp_page(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Perspective-correct the area inside ``quad`` into a flat rectangle."""
    tl, tr, br, bl = order_corners(quad)
    width = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    height = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    ratio = true_aspect_ratio(quad, (img.shape[1], img.shape[0]))
    if ratio is not None:
        # Keep the larger visible dimension and derive the other from the real ratio.
        if ratio < width / height:
            width = height * ratio
        else:
            height = width / ratio
    width, height = max(int(round(width)), 1), max(int(round(height)), 1)
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    matrix = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl], np.float32), dst)
    page = cv2.warpPerspective(img, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # Shave a hair off each edge so no sliver of the table survives along the border.
    my, mx = max(2, round(height * 0.006)), max(2, round(width * 0.006))
    return page[my : height - my, mx : width - mx] if height > 4 * my and width > 4 * mx else page


# ------------------------------------------------------------------------- rotation


def rotate(img: np.ndarray, degrees_clockwise: int) -> np.ndarray:
    degrees = degrees_clockwise % 360
    if degrees == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


_OSD_ROTATE = re.compile(r"Rotate:\s*(\d+)")
_OSD_CONF = re.compile(r"Orientation confidence:\s*([\d.]+)")


def detect_orientation(img: np.ndarray, tesseract: str | None) -> int:
    """Clockwise rotation (0/90/180/270) that makes the page's text upright.

    Uses Tesseract's orientation detection; returns 0 if Tesseract isn't installed,
    the page has too little text, or the result isn't confident.
    """
    if not tesseract:
        return 0
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, 1600 / max(gray.shape[:2]))
    if scale < 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    with tempfile.TemporaryDirectory(prefix="pscan-osd-") as tmp:
        path = Path(tmp) / "page.png"
        cv2.imwrite(str(path), gray)
        try:
            proc = subprocess.run(
                [tesseract, str(path), "stdout", "--psm", "0", "--dpi", "150"],
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("Orientation detection failed: %s", exc)
            return 0
    rot = _OSD_ROTATE.search(proc.stdout)
    conf = _OSD_CONF.search(proc.stdout)
    if not rot or not conf:
        return 0  # usually "Too few characters" on photos/blank pages
    if float(conf.group(1)) < OSD_MIN_CONFIDENCE:
        return 0
    return int(rot.group(1)) % 360


# ----------------------------------------------------------------------- enhancement


def _odd(value: float, minimum: int) -> int:
    n = max(minimum, int(round(value)))
    return n if n % 2 else n + 1


def _flatten(plane: np.ndarray) -> np.ndarray:
    """Even out lighting: divide by an estimate of the paper's brightness.

    The background is estimated on a small copy (it's smooth anyway) by dilating away
    the text and median-blurring, which removes shadows and makes the paper white.
    """
    h, w = plane.shape[:2]
    s = min(1.0, 800 / max(h, w))
    small = cv2.resize(plane, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else plane
    long_edge = max(small.shape[:2])
    k = _odd(long_edge / 100, 3)
    bg = cv2.dilate(small, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.medianBlur(bg, _odd(long_edge / 30, 5))
    if s < 1:
        bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.divide(plane, np.maximum(bg, 1), scale=255)


def _darken_ink(img: np.ndarray) -> np.ndarray:
    """Gentle contrast curve: keeps white paper white, makes text a little darker."""
    lut = np.clip(((np.arange(256) / 255.0) ** 1.6) * 255.0, 0, 255).astype(np.uint8)
    return cv2.LUT(img, lut)


def enhance(img: np.ndarray, mode: str) -> np.ndarray:
    """Return the page styled for ``mode``: BGR for color, single-channel for gray/bw."""
    if mode == "color":
        planes = [_flatten(p) for p in cv2.split(img)]
        return _darken_ink(cv2.merge(planes))
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    flat = _flatten(gray)
    if mode == "gray":
        return _darken_ink(flat)
    if mode == "bw":
        block = _odd(max(flat.shape[:2]) / 40, 15)
        return cv2.adaptiveThreshold(flat, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 15)
    raise ValueError(f"Unknown mode: {mode!r}")


def thumbnail(img: np.ndarray, long_edge: int) -> np.ndarray:
    scale = min(1.0, long_edge / max(img.shape[:2]))
    if scale >= 1.0:
        return img
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
