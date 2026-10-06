"""Combine page images into one PDF, searchable when Tesseract is available."""

from __future__ import annotations

import logging
import os
import re
import secrets
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import img2pdf
from pypdf import PdfWriter

from .sessions import RenderedPage

log = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_NAME = 120


@dataclass
class BuildResult:
    path: Path
    pages: int
    ocr_applied: bool
    ocr_error: str | None = None


def safe_stem(name: str | None, now: datetime | None = None) -> str:
    """A Windows-safe file name (without .pdf) from what the user typed, or a timestamp."""
    now = now or datetime.now()
    stem = (name or "").strip()
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = _INVALID_CHARS.sub("_", stem).strip(" .")
    stem = re.sub(r"\s+", " ", stem)[:MAX_NAME].strip(" .")
    if not stem or stem.upper() in _RESERVED:
        stem = now.strftime("Scan_%Y-%m-%d_%H-%M-%S")
    return stem


def unique_path(directory: Path, stem: str) -> Path:
    """``directory/stem.pdf``, or ``stem (2).pdf``, ``stem (3).pdf``... if taken."""
    candidate = directory / f"{stem}.pdf"
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({n}).pdf"
        n += 1
    return candidate


def _ocr_page(tesseract: str, page: RenderedPage, lang: str, workdir: Path) -> Path:
    """Run Tesseract on one page; returns a 1-page PDF with an invisible text layer."""
    out_base = workdir / page.path.stem
    proc = subprocess.run(
        [tesseract, str(page.path), str(out_base), "-l", lang, "--dpi", str(round(page.dpi)), "pdf"],
        capture_output=True,
        text=True,
        timeout=300,
        creationflags=_NO_WINDOW,
    )
    pdf = out_base.with_suffix(".pdf")
    if proc.returncode != 0 or not pdf.exists():
        message = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(message[-1] if message else f"tesseract exited with {proc.returncode}")
    return pdf


def _plain_page(page: RenderedPage, workdir: Path) -> Path:
    pdf = workdir / f"{page.path.stem}.plain.pdf"
    pdf.write_bytes(img2pdf.convert(str(page.path)))
    return pdf


def build_pdf(
    pages: list[RenderedPage],
    output_dir: Path,
    name: str | None = None,
    ocr: bool = True,
    tesseract: str | None = None,
    lang: str = "eng",
    workers: int = 4,
) -> BuildResult:
    """Build the PDF and save it into ``output_dir`` without overwriting anything."""
    if not pages:
        raise ValueError("There are no pages to save")
    output_dir.mkdir(parents=True, exist_ok=True)

    ocr_error = None
    if ocr and not tesseract:
        ocr_error = "Tesseract OCR is not installed"

    with tempfile.TemporaryDirectory(prefix="pscan-pdf-") as tmp:
        workdir = Path(tmp)
        page_pdfs: list[Path | None] = [None] * len(pages)
        ocr_ok = bool(ocr and tesseract)

        if ocr_ok:
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                futures = [pool.submit(_ocr_page, tesseract, p, lang, workdir) for p in pages]
                for i, future in enumerate(futures):
                    try:
                        page_pdfs[i] = future.result()
                    except Exception as exc:  # fall back to a plain page, keep going
                        ocr_ok = False
                        ocr_error = f"OCR failed on page {i + 1}: {exc}"
                        log.warning(ocr_error)

        for i, page in enumerate(pages):
            if page_pdfs[i] is None:
                page_pdfs[i] = _plain_page(page, workdir)

        writer = PdfWriter()
        for pdf in page_pdfs:
            writer.append(str(pdf))
        writer.add_metadata({"/Producer": "PScan", "/Creator": "PScan phone scanner"})

        # Write next to the destination, then rename: no half-written PDFs in the folder.
        final = unique_path(output_dir, safe_stem(name))
        partial = output_dir / f".{final.stem}.{secrets.token_hex(4)}.partial"
        try:
            with open(partial, "wb") as f:
                writer.write(f)
            os.replace(partial, final)
        finally:
            partial.unlink(missing_ok=True)

    log.info("Saved %s (%d pages, ocr=%s)", final, len(pages), ocr_ok)
    return BuildResult(path=final, pages=len(pages), ocr_applied=ocr_ok, ocr_error=ocr_error)
