"""Windows toast notifications (pairing code, scan saved)."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

APP_ID = "PScan"


class Notifier:
    """Shows Windows toasts. Failures are logged and never break a scan."""

    def _show(self, title: str, message: str, launch: str = "", long: bool = False) -> None:
        try:
            from winotify import Notification, audio

            toast = Notification(
                app_id=APP_ID,
                title=title,
                msg=message,
                duration="long" if long else "short",
                launch=launch,
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
        except Exception:
            log.exception("Could not show notification %r", title)

    def pairing_code(self, code: str, device_name: str) -> None:
        pretty = f"{code[:3]} {code[3:]}"
        self._show(
            f"PScan pairing code: {pretty}",
            f"Enter this code on {device_name} to connect it to this PC. It expires in 2 minutes.",
            long=True,
        )

    def scan_saved(self, path: Path, pages: int, ocr_applied: bool, ocr_error: str | None) -> None:
        detail = f"{pages} page{'s' if pages != 1 else ''}"
        if ocr_applied:
            detail += ", searchable"
        elif ocr_error:
            detail += f" (not searchable: {ocr_error})"
        self._show(f"Scan saved: {path.name}", f"{detail}. Click to open.", launch=path.resolve().as_uri())

    def message(self, title: str, message: str) -> None:
        self._show(title, message)


class NullNotifier(Notifier):
    """Used in tests: records instead of showing toasts."""

    def __init__(self):
        self.shown: list[tuple[str, str]] = []

    def _show(self, title: str, message: str, launch: str = "", long: bool = False) -> None:
        self.shown.append((title, message))
