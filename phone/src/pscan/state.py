"""What the app remembers between launches (paired PC, current scan, preferences)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

MODES = {"color": "Color", "gray": "Grayscale", "bw": "Black & white"}
PAPERS = {
    "A4": "A4 · 210 × 297 mm",
    "Letter": "Letter · 8.5 × 11 in",
    "Long": "Long bond · 8.5 × 13 in",
    "Legal": "Legal · 8.5 × 14 in",
    "Original": "Original shape",
}
DEFAULT_PAPER = "A4"


@dataclass
class PairedServer:
    server_id: str
    name: str
    host: str
    port: int
    token: str


@dataclass
class PendingUpload:
    """A photo taken but not yet on the PC (kept so it survives the app being closed)."""

    file: str
    replace: str | None = None


@dataclass
class AppState:
    server: PairedServer | None = None
    session_id: str | None = None
    pending: list[PendingUpload] = field(default_factory=list)
    mode: str = "color"
    paper: str = DEFAULT_PAPER
    ocr: bool = True

    @classmethod
    def load(cls, path: Path) -> AppState:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.exception("Settings file unreadable; starting fresh")
            return cls()
        server = raw.get("server")
        return cls(
            server=PairedServer(**server) if server else None,
            session_id=raw.get("session_id"),
            pending=[PendingUpload(**p) for p in raw.get("pending", [])],
            mode=raw.get("mode") if raw.get("mode") in MODES else "color",
            paper=raw.get("paper") if raw.get("paper") in PAPERS else DEFAULT_PAPER,
            ocr=bool(raw.get("ocr", True)),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")
        tmp.replace(path)
