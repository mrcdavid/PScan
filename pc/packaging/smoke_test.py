r"""Prove the built PScan.exe actually works, not just the source.

Starts the frozen exe in a temp home, pre-seeds a paired device, then exercises the
whole scan flow over HTTP: health, upload, finish with OCR (searchable A4 PDF) and
finish without OCR. Run by build_windows.ps1; exits non-zero on any failure.

    pc\.venv\Scripts\python packaging\smoke_test.py dist\PScan\PScan.exe
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from pypdf import PdfReader

TOKEN = "smoke-test-token"
VERSION = "0.4.0"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_page_jpeg() -> bytes:
    img = np.full((1100, 850, 3), 245, np.uint8)
    for i, line in enumerate(["HELLO PSCAN", "The quick brown fox", "Invoice 12345 total 678.90"] * 4):
        y = 120 + i * 80
        if y > 1040:
            break
        cv2.putText(img, line, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 2, cv2.LINE_AA)
    return cv2.imencode(".jpg", img)[1].tobytes()


def api(port: int, method: str, path: str, data=None, ctype=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    if ctype:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read()
    return json.loads(body) if body else {}


def wait_healthy(port: int, deadline: float) -> dict:
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(0.5)
    raise SystemExit("PScan.exe did not become healthy in time")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: smoke_test.py <path to PScan.exe>")
        return 2
    exe = Path(sys.argv[1]).resolve()
    if not exe.is_file():
        print(f"not found: {exe}")
        return 2

    port = free_port()
    # The config template must be shipped next to the exe (it seeds the user's settings).
    assert (exe.parent / "_internal" / "config.template.toml").is_file(), "config.template.toml not bundled"

    with tempfile.TemporaryDirectory(prefix="pscan-smoke-") as tmp:
        home = Path(tmp)
        (home / "data").mkdir(parents=True)
        # Only set the port (no output_dir), so the exe uses its installed default:
        # %USERPROFILE%\PScan Scans, which we point at this temp home.
        (home / "config.toml").write_text(f"port = {port}\nocr = true\n", encoding="utf-8")
        (home / "data" / "devices.json").write_text(
            json.dumps([{"name": "Smoke phone", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}]),
            encoding="utf-8",
        )

        env = {
            **__import__("os").environ,
            "PSCAN_HOME": str(home),
            "USERPROFILE": str(home),
            "PSCAN_QUIET": "1",
        }
        proc = subprocess.Popen(
            [str(exe), "--no-tray", "--host", "127.0.0.1"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            health = wait_healthy(port, time.time() + 40)
            assert health.get("version") == VERSION, f"version {health.get('version')} != {VERSION}"
            assert health.get("ocr_available") is True, "bundled Tesseract not found by the exe"
            print(f"  health OK: {health['name']} v{health['version']}, OCR available")

            # Searchable PDF.
            sid = api(port, "POST", "/api/sessions")["id"]
            api(port, "POST", f"/api/sessions/{sid}/pages", data=make_page_jpeg(), ctype="image/jpeg")
            res = api(
                port,
                "POST",
                f"/api/sessions/{sid}/finish",
                data=json.dumps({"ocr": True}).encode(),
                ctype="application/json",
            )
            assert res["ocr_applied"], f"OCR did not run: {res.get('ocr_error')}"
            assert res["folder"].replace("\\", "/").endswith("PScan Scans"), f"output went to {res['folder']}"
            pdf = Path(res["folder"]) / res["filename"]
            reader = PdfReader(str(pdf))
            box = reader.pages[0].mediabox
            w, h = round(float(box.width)), round(float(box.height))
            # A4 is 595x842 pt; a tiny test image at integer DPI can be a point off. This
            # still clearly distinguishes A4 from Letter (612x792).
            assert abs(w - 595) <= 3 and abs(h - 842) <= 3, f"page is {w}x{h} pt, not A4 (595x842)"
            text = reader.pages[0].extract_text().upper()
            assert "HELLO PSCAN" in text, "OCR text not found in the PDF"
            print(f"  OCR PDF OK: {pdf.name}, A4, searchable")

            # Plain PDF (img2pdf path).
            sid = api(port, "POST", "/api/sessions")["id"]
            api(port, "POST", f"/api/sessions/{sid}/pages", data=make_page_jpeg(), ctype="image/jpeg")
            res = api(
                port,
                "POST",
                f"/api/sessions/{sid}/finish",
                data=json.dumps({"ocr": False}).encode(),
                ctype="application/json",
            )
            assert (Path(res["folder"]) / res["filename"]).is_file(), "non-OCR PDF not written"
            print(f"  non-OCR PDF OK: {res['filename']}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("Smoke test PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
