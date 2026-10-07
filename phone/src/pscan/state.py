"""What the app remembers between launches (paired PCs, current scan, preferences)."""

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
    servers: list[PairedServer] = field(default_factory=list)  # every PC this phone is paired with
    active_id: str | None = None  # the PC scans currently go to
    session_id: str | None = None  # the unfinished scan on the active PC
    pending: list[PendingUpload] = field(default_factory=list)
    mode: str = "color"
    paper: str = DEFAULT_PAPER
    ocr: bool = True

    @property
    def server(self) -> PairedServer | None:
        """The active PC, if any."""
        return self.find(self.active_id)

    def find(self, server_id: str | None) -> PairedServer | None:
        return next((s for s in self.servers if s.server_id == server_id), None)

    @classmethod
    def load(cls, path: Path) -> AppState:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.exception("Settings file unreadable; starting fresh")
            return cls()
        servers = [PairedServer(**s) for s in raw.get("servers", [])]
        if not servers and raw.get("server"):  # settings from 0.2.x and earlier: one PC only
            servers = [PairedServer(**raw["server"])]
        active_id = raw.get("active_id")
        if not any(s.server_id == active_id for s in servers):
            active_id = servers[0].server_id if servers else None
        return cls(
            servers=servers,
            active_id=active_id,
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
