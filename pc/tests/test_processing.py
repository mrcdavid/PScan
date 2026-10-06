import io

import cv2
import numpy as np
import pytest
from PIL import Image

from pscan_samples import PAGE_H, PAGE_W, camera_corners, make_page, make_photo
from pscan_server import processing
from pscan_server.config import load_config


@pytest.mark.parametrize(
    "corners",
    [
        ((420, 140), (1180, 210), (1230, 1080), (330, 1010)),  # tilted, perspective
        ((300, 100), (1100, 100), (1100, 1130), (300, 1130)),  # straight on
        ((500, 60), (1350, 240), (1150, 1150), (250, 950)),  # strongly rotated
    ],
)
def test_detect_page_finds_corners(corners):
    photo, truth = make_photo(corners)
    quad = processing.detect_page(photo)
    assert quad is not None
    tolerance = 0.02 * np.hypot(*photo.shape[:2])
    assert np.abs(processing.order_corners(quad) - truth).max() < tolerance


def test_detect_page_with_shadow():
    photo, truth = make_photo(shadow=True)
    quad = processing.detect_page(photo)
    assert quad is not None
    assert np.abs(processing.order_corners(quad) - truth).max() < 0.02 * np.hypot(*photo.shape[:2])


@pytest.mark.parametrize(
    "pose",
    [
        dict(rx=0, ry=0, rz=0),  # straight on
        dict(rx=25, ry=15, rz=8),  # typical hand-held angle
        dict(rx=40, ry=-10, rz=-20),  # steep angle
        dict(rx=-30, ry=25, rz=95, distance=22),  # sideways and tilted
    ],
)
def test_warp_restores_page_proportions(pose):
    photo, truth = make_photo(camera_corners(**pose))
    warped = processing.warp_page(photo, truth)
    h, w = warped.shape[:2]
    ratio = min(w, h) / max(w, h)
    assert ratio == pytest.approx(PAGE_W / PAGE_H, rel=0.03)


def test_no_page_in_noise():
    rng = np.random.default_rng(1)
    noise = rng.integers(0, 255, (900, 1200, 3), dtype=np.uint8)
    assert processing.detect_page(noise) is None


def test_page_filling_the_frame_is_not_cropped():
    assert processing.detect_page(make_page()) is None


def test_load_image_applies_exif_rotation_and_limit():
    img = Image.new("RGB", (4000, 2000), "white")
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW to display
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    out = processing.load_image(buf.getvalue(), max_long_edge=3000)
    assert out.shape[:2] == (3000, 1500)  # now portrait, long edge limited


def test_load_image_rejects_garbage():
    with pytest.raises(processing.ImageDecodeError):
        processing.load_image(b"not an image", 3000)


@pytest.mark.parametrize("mode,ndim", [("color", 3), ("gray", 2), ("bw", 2)])
def test_enhance_modes(mode, ndim):
    photo, truth = make_photo(shadow=True)
    page = processing.warp_page(photo, truth)
    out = processing.enhance(page, mode)
    assert out.ndim == ndim
    assert out.shape[:2] == page.shape[:2]
    assert out.dtype == np.uint8
    if mode == "bw":
        assert set(np.unique(out)) <= {0, 255}


def test_enhance_removes_shadow():
    photo, truth = make_photo(shadow=True)
    page = processing.warp_page(photo, truth)
    gray = processing.enhance(page, "gray")
    # Compare paper brightness at the dark (left) and bright (right) margins.
    left = np.median(gray[200:900, 10:40])
    right = np.median(gray[200:900, -40:-10])
    raw = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
    assert abs(float(left) - float(right)) < 15
    assert abs(float(np.median(raw[200:900, 10:40])) - float(np.median(raw[200:900, -40:-10]))) > 40


def test_rotate():
    img = np.zeros((10, 20), np.uint8)
    assert processing.rotate(img, 90).shape == (20, 10)
    assert processing.rotate(img, 450).shape == (20, 10)
    assert processing.rotate(img, 180).shape == (10, 20)
    assert processing.rotate(img, 0) is img


def test_encode_jpeg_sets_dpi():
    img = make_page()
    data = processing.encode_jpeg(img, 85, dpi=100)
    with Image.open(io.BytesIO(data)) as im:
        assert round(im.info["dpi"][0]) == 100


TESSERACT = load_config().find_tesseract()


@pytest.mark.skipif(not TESSERACT, reason="Tesseract OCR is not installed")
def test_detect_orientation_of_sideways_page():
    page = make_page()
    sideways = cv2.rotate(page, cv2.ROTATE_90_COUNTERCLOCKWISE)
    correction = processing.detect_orientation(sideways, TESSERACT)
    assert correction == 90
    assert processing.detect_orientation(page, TESSERACT) == 0


A4 = 297 / 210


@pytest.mark.parametrize(
    "shape,landscape",
    [
        ((1414, 1000), False),  # already A4
        ((1380, 1000), False),  # slightly off (detection error): snapped
        ((1000, 1380), True),  # landscape A4-ish
        ((1294, 1000), False),  # Letter proportions: padded
        ((2000, 600), False),  # receipt: padded left/right
        ((900, 1200), True),  # 4:3 landscape photo: padded
    ],
)
def test_fit_to_paper_a4(shape, landscape):
    img = np.zeros((*shape, 3), np.uint8)
    out = processing.fit_to_paper(img, "A4")
    h, w = out.shape[:2]
    assert max(h, w) / min(h, w) == pytest.approx(A4, abs=0.002)
    assert (w > h) == landscape
    assert h >= shape[0] - 1 and w >= shape[1] - 1 or abs(max(h, w) / min(h, w) - A4) < 0.002


def test_fit_to_paper_pads_with_white_and_keeps_content():
    img = np.zeros((2000, 600), np.uint8)  # black receipt
    out = processing.fit_to_paper(img, "A4")
    assert out.shape == (2000, round(2000 / A4))
    assert out[:, 0].min() == 255 and out[:, -1].min() == 255  # white margins
    assert (out == 0).sum() == img.size  # every receipt pixel kept, none stretched


def test_fit_to_paper_original_and_other_sizes():
    img = np.zeros((900, 1200, 3), np.uint8)
    assert processing.fit_to_paper(img, "Original") is img
    out = processing.fit_to_paper(np.zeros((1000, 800), np.uint8), "Long")
    assert out.shape[0] / out.shape[1] == pytest.approx(13 / 8.5, abs=0.002)


def test_page_dpi_matches_paper():
    img = processing.fit_to_paper(np.zeros((2970, 2100), np.uint8), "A4")
    assert processing.page_dpi(img, "A4") == pytest.approx(254, abs=0.5)  # 2970 px over 11.69 in


@pytest.mark.parametrize("paper,size_in", [("A4", (8.268, 11.693)), ("Letter", (8.5, 11)), ("Long", (8.5, 13))])
def test_finalize_page_gives_exact_paper_size(paper, size_in):
    img = np.zeros((2333, 1777, 3), np.uint8)
    out, dpi = processing.finalize_page(img, paper)
    assert isinstance(dpi, int)
    h, w = out.shape[:2]
    assert (w / dpi, h / dpi) == pytest.approx(size_in, abs=0.004)
