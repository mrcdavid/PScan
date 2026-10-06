"""Everything the PScan app does, independent of how it is displayed.

The screen (an HTML page, see ``ui/``) shows ``snapshot()`` and sends actions back
through ``dispatch()``. All methods run on the app's asyncio event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from .client import ApiError, ConnectionFailed, NotFound, PScanClient, Unauthorized
from .discovery import FoundServer, discover
from .state import MODES, PAPERS, AppState, PairedServer, PendingUpload

log = logging.getLogger("pscan")

APP_VERSION = "0.2.1"  # fallback when the app metadata isn't available (tests, preview)
BUILD_YEAR = 2026


@dataclass
class Page:
    key: str  # local id, stable before the PC has assigned one
    server_id: str | None = None
    status: str = "waiting"  # waiting | uploading | ready | failed
    crop: bool = True
    cropped: bool = False
    file: Path | None = None  # photo not on the PC yet
    replace: str | None = None  # PC page this photo replaces (retake)
    thumb: bytes | None = None  # preview JPEG from the PC
    thumb_version: int = 0
    busy: bool = False  # an edit or preview refresh is in progress
    error: str | None = None


class Controller:
    def __init__(
        self,
        data_dir: Path,
        take_photo: Callable[[], Awaitable[Path | None]],
        device_name: str,
        app_version: str = APP_VERSION,
    ):
        self.take_photo = take_photo
        self.device_name = device_name
        self.app_version = app_version
        self.state_path = data_dir / "settings.json"
        self.state = AppState.load(self.state_path)

        # Photos taken earlier that never reached the PC.
        self.pages: list[Page] = [
            Page(key=uuid.uuid4().hex, file=Path(p.file), replace=p.replace, server_id=p.replace)
            for p in self.state.pending
            if Path(p.file).exists()
        ]
        self.client: PScanClient | None = None
        self.connected = False
        self.restored = False
        self.screen = "scan" if self.state.server else "connect"
        self.connection = ("connecting", "Connecting…") if self.state.server else ("offline", "")
        self.searching = False
        self.found: list[FoundServer] = []
        self.search_message = ""
        self.pairing: tuple[FoundServer, str, PScanClient] | None = None
        self.pair_busy = False
        self.pair_error = ""
        self.saving: dict = {"state": "idle"}
        self.refreshing = False
        self.toast: dict | None = None
        self.insets = {"top": 0, "bottom": 0}

        self.version = 0
        self.snapshot_json = b"{}"
        self.changed = threading.Condition()
        self.uploads_wanted = asyncio.Event()
        self.session_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self.notify()

    # ================================================================ plumbing

    def start(self) -> None:
        """Start the background work (call once the event loop is running)."""
        self._spawn(self.connection_loop())
        self._spawn(self.upload_worker())
        if not self.state.server:
            self._spawn(self.search_pcs())

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def run(self, fn, *args):
        """Run a blocking network call off the event loop."""
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    def save_state(self) -> None:
        self.state.pending = [PendingUpload(str(p.file), p.replace) for p in self.pages if p.file]
        try:
            self.state.save(self.state_path)
        except OSError:
            log.exception("Could not save settings")

    def show_toast(self, text: str, kind: str = "info") -> None:
        self.toast = {"id": (self.toast or {}).get("id", 0) + 1, "text": text, "kind": kind}
        self.notify()

    def set_insets(self, top: float, bottom: float) -> None:
        insets = {"top": round(top, 1), "bottom": round(bottom, 1)}
        if insets != self.insets:
            self.insets = insets
            self.notify()

    def notify(self) -> None:
        """Publish a new snapshot to the screen."""
        self.version += 1
        data = json.dumps(self.snapshot(), ensure_ascii=False).encode()
        with self.changed:
            self.snapshot_json = data
            self.changed.notify_all()

    def wait_for_change(self, since: int, timeout: float) -> tuple[int, bytes]:
        """Block (in a web-server thread) until the snapshot is newer than ``since``."""
        with self.changed:
            self.changed.wait_for(lambda: self.version > since, timeout=timeout)
            return self.version, self.snapshot_json

    def snapshot(self) -> dict:
        server = self.state.server
        uploading = sum(1 for p in self.pages if p.status != "ready")
        return {
            "v": self.version,
            "screen": self.screen,
            "insets": self.insets,
            "app": {"version": self.app_version, "year": BUILD_YEAR, "device": self.device_name},
            "connection": {"state": self.connection[0], "text": self.connection[1]},
            "server": {"name": server.name, "host": server.host} if server else None,
            "search": {
                "busy": self.searching,
                "message": self.search_message,
                "found": [{"id": f.server_id, "name": f.name, "host": f.host} for f in self.found],
            },
            "pair": {
                "server": self.pairing[0].name if self.pairing else "",
                "busy": self.pair_busy,
                "error": self.pair_error,
            },
            "pages": [
                {
                    "key": p.key,
                    "status": p.status,
                    "error": p.error,
                    "crop": p.crop,
                    "cropped": p.cropped,
                    "busy": p.busy,
                    "thumb": f"/thumb/{p.key}?v={p.thumb_version}" if p.thumb else None,
                }
                for p in self.pages
            ],
            "pending": uploading,
            "options": {
                "mode": self.state.mode,
                "paper": self.state.paper,
                "ocr": self.state.ocr,
                "modes": [{"id": k, "label": v} for k, v in MODES.items()],
                "papers": [{"id": k, "label": v} for k, v in PAPERS.items()],
            },
            "refreshing": self.refreshing,
            "saving": self.saving,
            "toast": self.toast,
        }

    def thumb(self, key: str) -> bytes | None:
        page = next((p for p in self.pages if p.key == key), None)
        return page.thumb if page else None

    def page(self, key: str) -> Page | None:
        return next((p for p in self.pages if p.key == key), None)

    # ================================================================ actions

    async def dispatch(self, name: str, args: dict) -> None:
        """Handle an action sent by the screen."""
        handlers = {
            "search": self.search_pcs,
            "connect_manual": self.connect_manual,
            "pair_start": self.pair_start,
            "pair_finish": self.pair_finish,
            "pair_resend": self.pair_resend,
            "pair_back": self.pair_back,
            "add_page": self.add_page,
            "retake": self.retake_page,
            "rotate": self.rotate_page,
            "toggle_crop": self.toggle_crop,
            "move": self.move_page,
            "delete": self.delete_page,
            "clear_all": self.clear_all,
            "set_option": self.set_option,
            "save": self.save_pdf,
            "save_dismiss": self.save_dismiss,
            "disconnect": self.disconnect,
        }
        handler = handlers.get(name)
        if handler is None:
            log.warning("Unknown action %r", name)
            return
        try:
            await handler(**args)
        except Exception as exc:  # never let one action break the app
            log.exception("Action %s failed", name)
            self.show_toast(str(exc) or "Something went wrong.", "error")

    # ============================================================ connect/pair

    async def search_pcs(self) -> None:
        if self.searching:
            return
        self.searching, self.search_message = True, ""
        self.notify()
        try:
            self.found = await self.run(discover, 3.0)
        finally:
            self.searching = False
        if not self.found:
            self.search_message = (
                "No PC found. Check that PScan is running on the PC and that both are on the same network."
            )
        self.notify()

    async def connect_manual(self, host: str) -> None:
        host = (host or "").strip()
        if not host:
            return
        name, _, port = host.partition(":")
        client = PScanClient(name, int(port) if port.isdigit() else 8765)
        self.searching, self.search_message = True, ""
        self.notify()
        try:
            health = await self.run(client.health, 4)
        except ApiError as exc:
            self.search_message = str(exc)
            return
        finally:
            self.searching = False
            self.notify()
        server = FoundServer(health["server_id"], health["name"], client.host, client.port)
        await self._pair_with(server)

    async def pair_start(self, server_id: str) -> None:
        server = next((f for f in self.found if f.server_id == server_id), None)
        if server:
            await self._pair_with(server)

    async def pair_resend(self) -> None:
        if self.pairing:
            await self._pair_with(self.pairing[0])

    async def pair_back(self) -> None:
        self.pairing, self.pair_error = None, ""
        self.screen = "connect"
        self.notify()

    async def _pair_with(self, server: FoundServer) -> None:
        client = PScanClient(server.host, server.port)
        self.pair_busy, self.pair_error = True, ""
        self.notify()
        try:
            pair_id = await self.run(client.pair_start, self.device_name)
        except ApiError as exc:
            self.show_toast(str(exc), "error")
            return
        finally:
            self.pair_busy = False
            self.notify()
        self.pairing = (server, pair_id, client)
        self.screen = "pair"
        self.notify()

    async def pair_finish(self, code: str) -> None:
        if not self.pairing or self.pair_busy:
            return
        server, pair_id, client = self.pairing
        self.pair_busy, self.pair_error = True, ""
        self.notify()
        try:
            result = await self.run(client.pair_finish, pair_id, code or "")
        except ApiError as exc:
            self.pair_error = str(exc)
            return
        finally:
            self.pair_busy = False
            self.notify()
        self.pairing = None
        self.state.server = PairedServer(result["server_id"], result["name"], server.host, server.port, result["token"])
        self.state.session_id = None
        self.restored = True  # a fresh pairing has no scan to restore
        self.save_state()
        self.screen = "scan"
        self.notify()
        await self.try_connect()

    async def disconnect(self) -> None:
        await self.forget_pc("")

    async def forget_pc(self, message: str) -> None:
        self.state.server = None
        self.state.session_id = None
        self.client = None
        self.connected = False
        self.connection = ("offline", "")
        for page in self.pages:
            if page.file:
                page.file.unlink(missing_ok=True)
        self.pages = []
        self.save_state()
        self.screen = "connect"
        self.notify()
        if message:
            self.show_toast(message, "error")
        await self.search_pcs()

    # ============================================================== connection

    def set_connection(self, state: str, text: str) -> None:
        if self.connection != (state, text):
            self.connection = (state, text)
            self.notify()

    async def connection_loop(self) -> None:
        while True:
            if self.state.server:
                if not self.connected:
                    await self.try_connect()
                else:
                    try:
                        await self.run(self.client.health, 4)
                    except ApiError:
                        self.connected = False
                        self.set_connection("offline", f"Lost {self.state.server.name}, reconnecting…")
            await asyncio.sleep(5 if not self.connected else 20)

    async def try_connect(self) -> bool:
        server = self.state.server
        if server is None:
            return False
        if self.connection[0] != "offline":
            self.set_connection("connecting", f"Connecting to {server.name}…")
        client = PScanClient(server.host, server.port, server.token)
        try:
            health = await self.run(client.health, 3)
            if health.get("server_id") != server.server_id:
                raise ConnectionFailed("A different PC answered at the old address.")
        except ApiError:
            # The PC's IP may have changed (new network, hotspot...). Look for it by id.
            found = await self.run(lambda: discover(3.0, want_id=server.server_id))
            match = next((f for f in found if f.server_id == server.server_id), None)
            if match is None:
                self.set_connection("offline", f"{server.name} not found. Is the PC on?")
                return False
            server.host, server.port = match.host, match.port
            self.save_state()
            client = PScanClient(server.host, server.port, server.token)
        try:
            await self.run(client.me)
        except Unauthorized:
            await self.forget_pc(f"{server.name} no longer knows this phone. Pair it again.")
            return False
        except ApiError as exc:
            self.set_connection("offline", str(exc))
            return False

        self.client = client
        self.connected = True
        self.set_connection("online", f"Connected to {server.name}")
        if not self.restored:
            await self.restore_session()
        self.uploads_wanted.set()
        return True

    async def restore_session(self) -> None:
        """After a restart: show the pages already on the PC for the unfinished scan."""
        self.restored = True
        sid = self.state.session_id
        if not sid:
            return
        try:
            session = await self.run(self.client.get_session, sid)
        except NotFound:
            self.state.session_id = None
            self.save_state()
            return
        except ApiError:
            self.restored = False  # try again on the next connection
            return
        known = {p.server_id for p in self.pages if p.server_id}
        restored = [
            Page(key=uuid.uuid4().hex, server_id=p["id"], status="ready", crop=p["crop"], cropped=p["cropped"])
            for p in session["pages"]
            if p["id"] not in known
        ]
        self.pages = restored + self.pages
        self.notify()
        for page in restored:
            await self.load_preview(page)

    # ================================================================= uploads

    async def ensure_session(self) -> str:
        async with self.session_lock:  # never create two scans at once
            if not self.state.session_id:
                self.state.session_id = (await self.run(self.client.create_session))["id"]
                self.save_state()
            return self.state.session_id

    async def upload_worker(self) -> None:
        """Uploads pages one at a time, in order, retrying until they reach the PC."""
        while True:
            page = next((p for p in self.pages if p.file and p.status in ("waiting", "failed")), None)
            if page is None or not self.connected or self.client is None:
                self.uploads_wanted.clear()
                await self.uploads_wanted.wait()
                continue
            page.status, page.error = "uploading", None
            self.notify()
            try:
                info = await self._upload(page)
            except Unauthorized:
                await self.forget_pc("This PC no longer knows this phone. Pair it again.")
                continue
            except Exception as exc:  # ApiError, or e.g. the photo file vanished
                log.warning("Upload failed: %s", exc)
                if isinstance(exc, FileNotFoundError):
                    if page in self.pages:
                        self.pages.remove(page)
                    self.save_state()
                    self.notify()
                    continue
                page.status, page.error = "failed", str(exc)
                if isinstance(exc, ConnectionFailed):
                    self.connected = False
                    if self.state.server:
                        self.set_connection("offline", f"Can't reach {self.state.server.name}, retrying…")
                self.notify()
                await asyncio.sleep(3)
                continue
            if page not in self.pages:  # thrown away while it was uploading
                await self._delete_on_pc(info["id"])
                continue
            page.file.unlink(missing_ok=True)
            page.file, page.replace, page.error = None, None, None
            page.server_id = info["id"]
            page.status, page.crop, page.cropped = "ready", info["crop"], info["cropped"]
            self.save_state()
            self.notify()
            await self.sync_order()
            await self.load_preview(page)

    async def _upload(self, page: Page) -> dict:
        sid = await self.ensure_session()
        try:
            return await self.run(self.client.upload_page, sid, page.file, page.replace)
        except NotFound:
            # The scan expired on the PC, or the page being retaken is gone: add as new.
            try:
                await self.run(self.client.get_session, sid)
            except NotFound:
                self.state.session_id = None
                sid = await self.ensure_session()
            page.replace = None
            return await self.run(self.client.upload_page, sid, page.file, None)

    async def load_preview(self, page: Page) -> None:
        if not (page.server_id and self.client and self.state.session_id):
            return
        page.busy = True
        self.notify()
        try:
            page.thumb = await self.run(
                self.client.preview, self.state.session_id, page.server_id, self.state.mode, self.state.paper
            )
            page.thumb_version += 1
        except ApiError as exc:
            log.warning("Preview failed: %s", exc)
        finally:
            page.busy = False
            self.notify()

    async def sync_order(self) -> None:
        """Tell the PC the page order shown on the phone."""
        ids = [p.server_id for p in self.pages if p.server_id]
        if self.client and self.state.session_id and len(ids) > 1:
            try:
                await self.run(self.client.reorder, self.state.session_id, ids)
            except ApiError as exc:
                log.warning("Reorder failed: %s", exc)

    async def _delete_on_pc(self, pid: str | None) -> None:
        if pid and self.client and self.state.session_id:
            try:
                await self.run(self.client.delete_page, self.state.session_id, pid)
            except NotFound:
                pass

    # ============================================================ page actions

    def _editable(self) -> bool:
        return self.saving.get("state") != "saving"

    async def add_page(self) -> None:
        if not self._editable():
            return
        try:
            photo = await self.take_photo()
        except PermissionError as exc:
            self.show_toast(str(exc), "error")
            return
        if photo is None:
            return
        self.pages.append(Page(key=uuid.uuid4().hex, file=photo))
        self.save_state()
        self.notify()
        self.uploads_wanted.set()

    async def retake_page(self, key: str) -> None:
        page = self.page(key)
        if page is None or page.status == "uploading" or not self._editable():
            return
        photo = await self.take_photo()
        if photo is None:
            return
        if page not in self.pages or page.status == "uploading":
            photo.unlink(missing_ok=True)
            return
        if page.file:
            page.file.unlink(missing_ok=True)
        page.file = photo
        page.replace = page.server_id
        page.status, page.thumb, page.error = "waiting", None, None
        self.save_state()
        self.notify()
        self.uploads_wanted.set()

    async def _edit(self, page: Page, rotate: int | None = None, crop: bool | None = None) -> None:
        page.busy = True
        self.notify()
        try:
            info = await self.run(self.client.update_page, self.state.session_id, page.server_id, rotate, crop)
        except ApiError as exc:
            page.busy = False
            self.notify()
            self.show_toast(str(exc), "error")
            return
        page.crop = info["crop"]
        await self.load_preview(page)

    async def rotate_page(self, key: str) -> None:
        page = self.page(key)
        if page and page.status == "ready" and not page.busy and self._editable():
            await self._edit(page, rotate=90)

    async def toggle_crop(self, key: str) -> None:
        page = self.page(key)
        if page and page.status == "ready" and page.cropped and not page.busy and self._editable():
            await self._edit(page, crop=not page.crop)

    async def move_page(self, key: str, delta: int) -> None:
        page = self.page(key)
        if page is None or not self._editable():
            return
        i = self.pages.index(page)
        j = i + int(delta)
        if 0 <= j < len(self.pages):
            self.pages[i], self.pages[j] = self.pages[j], self.pages[i]
            self.save_state()
            self.notify()
            await self.sync_order()

    async def delete_page(self, key: str) -> None:
        page = self.page(key)
        if page is None or page.status == "uploading" or not self._editable():
            return
        self.pages.remove(page)
        if page.file:
            page.file.unlink(missing_ok=True)
        self.save_state()
        self.notify()
        if page.server_id:
            try:
                await self._delete_on_pc(page.server_id)
            except ApiError as exc:
                log.warning("Delete failed: %s", exc)

    async def clear_all(self) -> None:
        if not self.pages or not self._editable():
            return
        if any(p.status == "uploading" for p in self.pages):
            self.show_toast("A page is uploading right now. Try again in a moment.")
            return
        sid = self.state.session_id
        for page in self.pages:
            if page.file:
                page.file.unlink(missing_ok=True)
        self.pages = []
        self.state.session_id = None
        self.save_state()
        self.notify()
        if sid and self.client:
            try:
                await self.run(self.client.delete_session, sid)
            except ApiError:
                pass

    async def set_option(self, mode: str | None = None, paper: str | None = None, ocr: bool | None = None) -> None:
        refresh = False
        if mode in MODES and mode != self.state.mode:
            self.state.mode, refresh = mode, True
        if paper in PAPERS and paper != self.state.paper:
            self.state.paper, refresh = paper, True
        if ocr is not None:
            self.state.ocr = bool(ocr)
        self.save_state()
        self.notify()
        if refresh:
            # Previews show the chosen style and paper size.
            self.refreshing = True
            self.notify()
            try:
                for page in list(self.pages):
                    if page.status == "ready" and page in self.pages:
                        await self.load_preview(page)
            finally:
                self.refreshing = False
                self.notify()

    # ==================================================================== save

    async def save_pdf(self, name: str = "") -> None:
        if not self.pages or not self._editable():
            return
        waiting = sum(1 for p in self.pages if p.status != "ready")
        if waiting:
            text = (
                "Pages will upload as soon as the PC is reachable."
                if not self.connected
                else f"{waiting} page(s) are still uploading. Try again in a moment."
            )
            self.show_toast(text, "error" if not self.connected else "info")
            return
        server = self.state.server
        self.saving = {"state": "saving", "ocr": self.state.ocr, "server": server.name}
        self.notify()
        try:
            await self.sync_order()
            result = await self.run(
                self.client.finish,
                self.state.session_id,
                (name or "").strip(),
                self.state.mode,
                self.state.ocr,
                self.state.paper,
            )
        except ApiError as exc:
            self.saving = {"state": "error", "message": str(exc)}
            self.notify()
            return
        self.pages = []
        self.state.session_id = None
        self.save_state()
        note = ""
        if self.state.ocr and not result.get("ocr_applied"):
            note = f"The text isn't searchable: {result.get('ocr_error') or 'OCR failed'}."
        self.saving = {
            "state": "done",
            "filename": result["filename"],
            "folder": result["folder"],
            "pages": result["pages"],
            "paper": result.get("paper", self.state.paper),
            "server": server.name,
            "note": note,
        }
        self.notify()

    async def save_dismiss(self) -> None:
        self.saving = {"state": "idle"}
        self.notify()
