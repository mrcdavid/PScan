"""Scan sessions stored on disk, so nothing is lost if the phone app or the PC restarts.

Layout: data/sessions/<session id>/
    session.json        page order + per-page settings
    <page id>.orig.jpg  the uploaded photo (upright, size-limited)
    <page id>.warp.jpg  the page after cropping/straightening (before rotation)
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import processing
from .config import MODES, Config

log = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[0-9a-f]{16}$")
PREVIEW_EDGE = 480
SESSION_MAX_AGE = 24 * 3600


class NotFound(KeyError):
    pass


def _new_id() -> str:
    return secrets.token_hex(8)


def _check_id(value: str) -> str:
    if not _ID_RE.match(value or ""):
        raise NotFound(value)
    return value


@dataclass
class RenderedPage:
    path: Path
    dpi: float


class SessionStore:
    def __init__(self, config: Config):
        self.config = config
        self.root = config.sessions_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ helpers

    def _dir(self, sid: str) -> Path:
        path = self.root / _check_id(sid)
        if not (path / "session.json").exists():
            raise NotFound(sid)
        return path

    def _load(self, sid: str) -> dict:
        return json.loads((self._dir(sid) / "session.json").read_text(encoding="utf-8"))

    def _save(self, session: dict) -> None:
        session["updated"] = time.time()
        path = self.root / session["id"] / "session.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(session, indent=1), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _find_page(session: dict, pid: str) -> dict:
        for page in session["pages"]:
            if page["id"] == pid:
                return page
        raise NotFound(pid)

    @staticmethod
    def public_page(page: dict) -> dict:
        """A page as sent to the phone."""
        return {
            "id": page["id"],
            "rotation": page["rotation"],
            "auto_rotation": page["auto_rotation"],
            "crop": page["crop"],
            "cropped": page["quad"] is not None,
        }

    @classmethod
    def public(cls, session: dict) -> dict:
        """The session as sent to the phone."""
        return {"id": session["id"], "pages": [cls.public_page(p) for p in session["pages"]]}

    # ---------------------------------------------------------------- sessions

    def create(self) -> dict:
        with self._lock:
            sid = _new_id()
            (self.root / sid).mkdir(parents=True)
            session = {"id": sid, "created": time.time(), "pages": []}
            self._save(session)
            log.info("Session %s created", sid)
            return session

    def get(self, sid: str) -> dict:
        with self._lock:
            return self._load(sid)

    def delete(self, sid: str) -> None:
        with self._lock:
            shutil.rmtree(self._dir(sid), ignore_errors=True)

    def cleanup(self, max_age: float = SESSION_MAX_AGE) -> int:
        """Delete sessions untouched for ``max_age`` seconds. Returns how many."""
        removed = 0
        now = time.time()
        with self._lock:
            for path in self.root.iterdir():
                meta = path / "session.json"
                try:
                    updated = json.loads(meta.read_text(encoding="utf-8")).get("updated", 0)
                except (OSError, ValueError):
                    updated = path.stat().st_mtime
                if now - updated > max_age:
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
        if removed:
            log.info("Cleaned up %d old session(s)", removed)
        return removed

    # ------------------------------------------------------------------- pages

    def add_page(self, sid: str, data: bytes, replace: str | None = None) -> dict:
        """Process an uploaded photo and add it (or swap it in for ``replace``)."""
        cfg = self.config
        with self._lock:  # fail fast on a bad session/page id before the slow part
            session = self._load(sid)
            if replace is not None:
                self._find_page(session, replace)
        # Heavy work happens outside the lock.
        original = processing.load_image(data, cfg.max_long_edge)
        quad = processing.detect_page(original)
        warped = processing.warp_page(original, quad) if quad is not None else original
        auto_rotation = processing.detect_orientation(warped, cfg.find_tesseract())

        with self._lock:
            session = self._load(sid)
            directory = self._dir(sid)
            if replace is not None:
                page = self._find_page(session, replace)
                pid = page["id"]
            else:
                pid = _new_id()
                page = {"id": pid}
                session["pages"].append(page)
            page.update(
                rotation=0,
                auto_rotation=auto_rotation,
                crop=True,
                quad=quad.tolist() if quad is not None else None,
            )
            (directory / f"{pid}.orig.jpg").write_bytes(processing.encode_jpeg(original, 92))
            (directory / f"{pid}.warp.jpg").write_bytes(processing.encode_jpeg(warped, 92))
            self._save(session)
            log.info(
                "Session %s: page %s %s (cropped=%s, auto-rotate=%d)",
                sid,
                pid,
                "replaced" if replace else "added",
                quad is not None,
                auto_rotation,
            )
            return page

    def update_page(self, sid: str, pid: str, rotate: int | None = None, crop: bool | None = None) -> dict:
        """Rotate a page by ``rotate`` degrees (clockwise) and/or turn auto-crop on/off."""
        with self._lock:
            session = self._load(sid)
            page = self._find_page(session, pid)
            if rotate:
                page["rotation"] = (page["rotation"] + int(rotate)) % 360
            if crop is not None:
                page["crop"] = bool(crop)
            self._save(session)
            return page

    def delete_page(self, sid: str, pid: str) -> None:
        with self._lock:
            session = self._load(sid)
            page = self._find_page(session, pid)
            session["pages"].remove(page)
            for suffix in (".orig.jpg", ".warp.jpg"):
                (self._dir(sid) / f"{pid}{suffix}").unlink(missing_ok=True)
            self._save(session)

    def reorder(self, sid: str, page_ids: list[str]) -> dict:
        with self._lock:
            session = self._load(sid)
            current = {p["id"]: p for p in session["pages"]}
            if sorted(page_ids) != sorted(current):
                raise ValueError("page_ids must list every page exactly once")
            session["pages"] = [current[pid] for pid in page_ids]
            self._save(session)
            return session

    # --------------------------------------------------------------- rendering

    def _page_image(self, sid: str, page: dict):
        """The page as it should look before mode styling: cropped (or not) and rotated."""
        directory = self._dir(sid)
        use_warp = page["crop"] and page["quad"] is not None
        name = f"{page['id']}.warp.jpg" if use_warp else f"{page['id']}.orig.jpg"
        img = processing.decode_jpeg((directory / name).read_bytes())
        return processing.rotate(img, page["auto_rotation"] + page["rotation"])

    @staticmethod
    def _check_style(mode: str, paper: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode!r}")
        if paper not in processing.PAPER_NAMES:
            raise ValueError(f"Unknown paper size: {paper!r}")

    def render_preview(self, sid: str, pid: str, mode: str, paper: str = "A4") -> bytes:
        """Small JPEG showing the page as it will look in the PDF."""
        self._check_style(mode, paper)
        with self._lock:
            session = self._load(sid)
            page = dict(self._find_page(session, pid))
        img = processing.thumbnail(self._page_image(sid, page), PREVIEW_EDGE)
        img = processing.fit_to_paper(processing.enhance(img, mode), paper)
        return processing.encode_jpeg(img, 75)

    def render_final(self, sid: str, mode: str, out_dir: Path, paper: str = "A4") -> list[RenderedPage]:
        """Write every page, full size and styled, as numbered JPEGs into ``out_dir``."""
        self._check_style(mode, paper)
        with self._lock:
            pages = [dict(p) for p in self._load(sid)["pages"]]
        rendered = []
        for index, page in enumerate(pages, start=1):
            img = processing.enhance(self._page_image(sid, page), mode)
            img, dpi = processing.finalize_page(img, paper)
            path = out_dir / f"page-{index:03d}.jpg"
            path.write_bytes(processing.encode_jpeg(img, self.config.jpeg_quality, dpi))
            rendered.append(RenderedPage(path=path, dpi=dpi))
        return rendered
