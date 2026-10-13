"""Settings (config.toml) and on-disk locations for the PScan PC server.

Two run modes:
* **source** (``python -m pscan_server`` from the repo): ``config.toml`` and ``data/`` live
  next to the code, exactly as during development.
* **installed** (the packaged ``PScan.exe``, i.e. ``sys.frozen``): per-user folders under
  ``%LOCALAPPDATA%\\PScan`` and Scans under ``%USERPROFILE%\\PScan Scans``, because an app in
  Program Files can't write beside its own files. ``PSCAN_HOME`` overrides the home folder
  (used by the packaging smoke test).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sys
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


def is_frozen() -> bool:
    """True when running as the packaged PScan.exe rather than from source."""
    return bool(getattr(sys, "frozen", False))


def installed_mode() -> bool:
    """Use per-user folders? True for the packaged exe, or when PSCAN_HOME is set (tests)."""
    return is_frozen() or "PSCAN_HOME" in os.environ


def app_dir() -> Path:
    """Folder of the running PScan.exe (installed) or the repo's ``pc/`` folder (source)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return PC_DIR


def home_dir() -> Path:
    """Where the installed app keeps config.toml and data/."""
    override = os.environ.get("PSCAN_HOME")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "PScan"


def _bundled_config_template() -> Path | None:
    """The config.toml shipped inside the exe, copied to the user's home on first run.

    Only the PyInstaller bundle provides one; from source there is no template (and no
    seeding), so the repo's own config.toml is never copied into a user's home folder.
    """
    base = getattr(sys, "_MEIPASS", None)  # PyInstaller's data folder
    if not base:
        return None
    candidate = Path(base) / "config.template.toml"
    return candidate if candidate.exists() else None


def _default_output_dir(installed: bool, config_path: Path) -> Path:
    if installed:
        profile = os.environ.get("USERPROFILE") or str(Path.home())
        return Path(profile) / "PScan Scans"
    return (config_path.parent / "../Scans").resolve()


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
    config_path: Path | None = None

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

    def save_output_dir(self, new_dir: Path) -> None:
        """Point PScan at a new Scans folder and persist it to config.toml (no restart)."""
        new_dir = Path(new_dir)
        new_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = new_dir
        if self.config_path is None:
            return
        # Store with forward slashes (valid on Windows, and no TOML backslash-escaping).
        line = f"output_dir = {json.dumps(new_dir.as_posix())}"
        text = self.config_path.read_text(encoding="utf-8") if self.config_path.exists() else ""
        if re.search(r"(?m)^\s*output_dir\s*=.*$", text):
            text = re.sub(r"(?m)^\s*output_dir\s*=.*$", line, text, count=1)
        else:
            text = (text.rstrip() + "\n" + line + "\n") if text else (line + "\n")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.config_path)

    def find_tesseract(self) -> str | None:
        """Path to tesseract.exe, or None if it isn't available.

        Prefers a copy bundled next to the installed exe, then an explicit config path,
        then the system install. Looked up on every call, so installing Tesseract (or an
        explicit path change) takes effect without a restart.
        """
        if self.tesseract_path:
            return self.tesseract_path if Path(self.tesseract_path).is_file() else None
        bundled = app_dir() / "tesseract" / "tesseract.exe"
        if bundled.is_file():
            return str(bundled)
        found = shutil.which("tesseract")
        if found:
            return found
        for candidate in _TESSERACT_CANDIDATES:
            if candidate.is_file():
                return str(candidate)
        return None


def load_config(path: Path | None = None, data_dir: Path | None = None) -> Config:
    installed = installed_mode()
    if path is None:
        path = (home_dir() / "config.toml") if installed else CONFIG_PATH
    if data_dir is None:
        data_dir = (home_dir() / "data") if installed else DATA_DIR

    # First run of the installed app: seed config.toml from the bundled template.
    if installed and not path.exists():
        template = _bundled_config_template()
        path.parent.mkdir(parents=True, exist_ok=True)
        if template:
            shutil.copyfile(template, path)

    raw = {}
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)

    if "output_dir" in raw:
        output_dir = Path(raw["output_dir"])
        if not output_dir.is_absolute():
            output_dir = (path.parent / output_dir).resolve()
    else:
        output_dir = _default_output_dir(installed, path)

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
        config_path=path,
    )
