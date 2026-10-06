from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pscan_server.config import Config  # noqa: E402

PAGE_W, PAGE_H = 850, 1100  # Letter proportions

LINES = [
    "PSCAN TEST DOCUMENT",
    "The quick brown fox jumps over",
    "the lazy dog near the river bank.",
    "Invoice number 12345 total 678.90",
    "Please keep this page for records.",
    "HELLO PSCAN",
]


def make_page(text: bool = True) -> np.ndarray:
    page = np.full((PAGE_H, PAGE_W, 3), 245, np.uint8)
    if text:
        for i, line in enumerate(LINES * 3):
            y = 110 + i * 52
            if y > PAGE_H - 60:
                break
            cv2.putText(page, line, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (20, 20, 20), 2, cv2.LINE_AA)
    return page


def camera_corners(rx=25.0, ry=15.0, rz=8.0, distance=18.0, f=1400.0, size=(1600, 1200)):
    """Where a Letter page's corners land in a photo from a real (pinhole) camera.

    The page is tilted by rx/ry/rz degrees and held ``distance`` page-units away.
    Returns TL, TR, BR, BL pixel coordinates.
    """
    w, h = size
    half_w, half_h = 8.5 / 2, 11 / 2
    pts = np.array([[-half_w, -half_h, 0], [half_w, -half_h, 0], [half_w, half_h, 0], [-half_w, half_h, 0]])
    ax, ay, az = np.radians([rx, ry, rz])
    rot_x = np.array([[1, 0, 0], [0, np.cos(ax), -np.sin(ax)], [0, np.sin(ax), np.cos(ax)]])
    rot_y = np.array([[np.cos(ay), 0, np.sin(ay)], [0, 1, 0], [-np.sin(ay), 0, np.cos(ay)]])
    rot_z = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    cam = pts @ (rot_z @ rot_y @ rot_x).T + np.array([0, 0, distance])
    u = f * cam[:, 0] / cam[:, 2] + w / 2
    v = f * cam[:, 1] / cam[:, 2] + h / 2
    return tuple(zip(u.round(1), v.round(1), strict=True))


def make_photo(
    corners=None,
    size=(1600, 1200),
    shadow: bool = False,
    seed: int = 0,
):
    """A fake phone photo: a page in perspective on a dark, slightly noisy table.

    Returns (photo, true_corners) with corners ordered TL, TR, BR, BL.
    """
    rng = np.random.default_rng(seed)
    w, h = size
    if corners is None:
        corners = camera_corners(size=size)
    photo = np.full((h, w, 3), (60, 52, 45), np.uint8)
    photo = cv2.add(photo, rng.integers(0, 20, photo.shape, dtype=np.uint8))
    page = make_page()
    src = np.array([[0, 0], [PAGE_W, 0], [PAGE_W, PAGE_H], [0, PAGE_H]], np.float32)
    dst = np.array(corners, np.float32)
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(page, matrix, (w, h))
    mask = cv2.warpPerspective(np.full((PAGE_H, PAGE_W), 255, np.uint8), matrix, (w, h))
    photo[mask > 0] = warped[mask > 0]
    if shadow:
        gradient = np.linspace(0.45, 1.0, w, dtype=np.float32)[None, :, None]
        photo = (photo.astype(np.float32) * gradient).astype(np.uint8)
    return photo, dst


def to_jpeg(img: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return buf.tobytes()


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(
        server_name="TEST-PC",
        port=8765,
        discovery_port=8766,
        output_dir=tmp_path / "Scans",
        default_mode="color",
        ocr=False,
        ocr_lang="eng",
        tesseract_path="",
        max_long_edge=3000,
        jpeg_quality=85,
        data_dir=tmp_path / "data",
    )
