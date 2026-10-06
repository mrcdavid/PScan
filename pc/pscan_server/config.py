"""Settings (config.toml) and on-disk locations for the PScan PC server."""

from __future__ import annotations

import shutil
import socket
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

from .processing import PAPER_NAMES

PC_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PC_DIR / "config.toml"
DATA_DIR = PC_DIR / "data"

MODES = ("color", "gray", "bw")

_TESSERACT_CANDIDATES = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe",
)


@dataclass
class Config:
    server_name: str
    port: int
    discovery_port: int
    output_dir: Path
    default_mode: str
    ocr: bool
    ocr_lang: str
    tesseract_path: str
    max_long_edge: int
    jpeg_quality: int
    data_dir: Path
    paper: str = "A4"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def devices_path(self) -> Path:
        return self.data_dir / "devices.json"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.sessions_dir, self.logs_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def server_id(self) -> str:
        """A stable random id, so the phone recognises this PC even if its IP changes."""
        path = self.data_dir / "server_id.txt"
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            sid = uuid.uuid4().hex
            path.write_text(sid, encoding="utf-8")
            return sid

    def find_tesseract(self) -> str | None:
        """Path to tesseract.exe, or None if it isn't installed.

        Looked up on every call so installing Tesseract doesn't need a restart.
        """
        if self.tesseract_path:
            return self.tesseract_path if Path(self.tesseract_path).is_file() else None
        found = shutil.which("tesseract")
        if found:
            return found
        for candidate in _TESSERACT_CANDIDATES:
            if candidate.is_file():
                return str(candidate)
        return None


def load_config(path: Path = CONFIG_PATH, data_dir: Path = DATA_DIR) -> Config:
    raw = {}
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    output_dir = Path(raw.get("output_dir", "../Scans"))
    if not output_dir.is_absolute():
        output_dir = (path.parent / output_dir).resolve()

    mode = raw.get("default_mode", "color")
    if mode not in MODES:
        mode = "color"

    paper = raw.get("paper", "A4")
    if paper not in PAPER_NAMES:
        paper = "A4"

    return Config(
        server_name=raw.get("server_name") or socket.gethostname(),
        port=int(raw.get("port", 8765)),
        discovery_port=int(raw.get("discovery_port", 8766)),
        output_dir=output_dir,
        default_mode=mode,
        ocr=bool(raw.get("ocr", True)),
        ocr_lang=raw.get("ocr_lang", "eng") or "eng",
        tesseract_path=raw.get("tesseract_path", "") or "",
        max_long_edge=int(raw.get("max_long_edge", 3000)),
        jpeg_quality=int(raw.get("jpeg_quality", 85)),
        data_dir=data_dir,
        paper=paper,
    )
