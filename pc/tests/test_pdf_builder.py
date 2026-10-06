from datetime import datetime

import pytest
from pypdf import PdfReader

from pscan_samples import make_page
from pscan_server import processing
from pscan_server.config import load_config
from pscan_server.pdf_builder import build_pdf, safe_stem, unique_path
from pscan_server.sessions import RenderedPage

NOW = datetime(2026, 10, 6, 14, 30, 12)


@pytest.mark.parametrize(
    "name,expected",
    [
        (None, "Scan_2026-10-06_14-30-12"),
        ("", "Scan_2026-10-06_14-30-12"),
        ("   ", "Scan_2026-10-06_14-30-12"),
        ("Electric bill", "Electric bill"),
        ("Electric bill.pdf", "Electric bill"),
        ('a/b\\c:d*e?f"g<h>i|j', "a_b_c_d_e_f_g_h_i_j"),
        ("CON", "Scan_2026-10-06_14-30-12"),
        ("trailing dots...", "trailing dots"),
        ("x" * 300, "x" * 120),
    ],
)
def test_safe_stem(name, expected):
    assert safe_stem(name, NOW) == expected


def test_unique_path(tmp_path):
    assert unique_path(tmp_path, "Doc").name == "Doc.pdf"
    (tmp_path / "Doc.pdf").write_bytes(b"x")
    assert unique_path(tmp_path, "Doc").name == "Doc (2).pdf"
    (tmp_path / "Doc (2).pdf").write_bytes(b"x")
    assert unique_path(tmp_path, "Doc").name == "Doc (3).pdf"


def _render_pages(tmp_path, count):
    pages = []
    for i in range(count):
        img = processing.enhance(make_page(), "gray")
        dpi = processing.page_dpi(img)
        path = tmp_path / f"page-{i + 1:03d}.jpg"
        path.write_bytes(processing.encode_jpeg(img, 85, dpi))
        pages.append(RenderedPage(path, dpi))
    return pages


def test_build_pdf_without_ocr(tmp_path):
    out = tmp_path / "Scans"
    result = build_pdf(_render_pages(tmp_path, 3), out, name="My scan", ocr=False)
    assert result.path == out / "My scan.pdf"
    assert result.pages == 3 and not result.ocr_applied and result.ocr_error is None
    reader = PdfReader(result.path)
    assert len(reader.pages) == 3
    box = reader.pages[0].mediabox
    assert float(box.height) / 72 == pytest.approx(11, abs=0.05)  # long side = 11 inches
    assert not [p for p in out.iterdir() if p.suffix != ".pdf"]  # no temp files left


def test_build_pdf_never_overwrites(tmp_path):
    out = tmp_path / "Scans"
    first = build_pdf(_render_pages(tmp_path, 1), out, name="Same", ocr=False)
    second = build_pdf(_render_pages(tmp_path, 1), out, name="Same", ocr=False)
    assert first.path.name == "Same.pdf" and second.path.name == "Same (2).pdf"


def test_build_pdf_reports_missing_tesseract(tmp_path):
    result = build_pdf(_render_pages(tmp_path, 1), tmp_path / "Scans", ocr=True, tesseract=None)
    assert not result.ocr_applied
    assert "not installed" in result.ocr_error
    assert len(PdfReader(result.path).pages) == 1


def test_build_pdf_falls_back_when_ocr_fails(tmp_path):
    bogus = tmp_path / "tesseract.exe"  # not a real program
    bogus.write_text("")
    result = build_pdf(_render_pages(tmp_path, 2), tmp_path / "Scans", ocr=True, tesseract=str(bogus))
    assert not result.ocr_applied and result.ocr_error
    assert len(PdfReader(result.path).pages) == 2


def test_build_pdf_needs_pages(tmp_path):
    with pytest.raises(ValueError):
        build_pdf([], tmp_path)


TESSERACT = load_config().find_tesseract()


@pytest.mark.skipif(not TESSERACT, reason="Tesseract OCR is not installed")
def test_build_pdf_with_ocr_is_searchable(tmp_path):
    result = build_pdf(_render_pages(tmp_path, 2), tmp_path / "Scans", ocr=True, tesseract=TESSERACT)
    assert result.ocr_applied, result.ocr_error
    reader = PdfReader(result.path)
    assert len(reader.pages) == 2
    assert "HELLO PSCAN" in reader.pages[0].extract_text().upper()
