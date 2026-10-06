"""A tiny web server inside the app, bound to 127.0.0.1, that connects the HTML screen
(shown in a WebView) to the Python controller.

    GET  /?k=<key>          the screen (ui/index.html)
    GET  /ui/<file>         its CSS/JS/images
    GET  /api/state?since=N the controller's snapshot, waiting up to 20 s for a change
    POST /api/action        {"name": ..., "args": {...}}  -> run on the event loop
    GET  /thumb/<key>       page preview JPEG

Every request except the first page load must carry the random key, so other apps on
the phone can't drive PScan through this port.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .controller import Controller

log = logging.getLogger("pscan.bridge")

UI_DIR = Path(__file__).resolve().parent / "ui"
LONG_POLL_SECONDS = 20


class Bridge:
    def __init__(self, controller: Controller, loop: asyncio.AbstractEventLoop, ui_dir: Path = UI_DIR):
        self.controller = controller
        self.loop = loop
        self.ui_dir = ui_dir
        self.key = secrets.token_urlsafe(16)
        bridge = self

        class Handler(_Handler):
            pass

        Handler.bridge = bridge
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="pscan-bridge", daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/?k={self.key}"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()


class _Handler(BaseHTTPRequestHandler):
    bridge: Bridge
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep logcat quiet
        log.debug(fmt, *args)

    # ---------------------------------------------------------------- helpers

    def _send(self, status: int, body: bytes, content_type: str, cache: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=31536000, immutable" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _authorized(self, query: dict) -> bool:
        key = self.headers.get("X-PScan-Key") or query.get("k", [""])[0]
        return secrets.compare_digest(key, self.bridge.key)

    # ----------------------------------------------------------------- routes

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        path = url.path

        if path.startswith("/ui/"):
            return self._static(path[len("/ui/") :])
        if not self._authorized(query):
            return self._json(403, {"error": "forbidden"})
        if path == "/":
            return self._static("index.html")
        if path == "/api/state":
            since = int(query.get("since", ["0"])[0] or 0)
            _, body = self.bridge.controller.wait_for_change(since, LONG_POLL_SECONDS)
            return self._send(200, body, "application/json")
        if path.startswith("/thumb/"):
            data = self.bridge.controller.thumb(path[len("/thumb/") :])
            if data is None:
                return self._json(404, {"error": "no preview"})
            return self._send(200, data, "image/jpeg", cache=True)
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if not self._authorized(parse_qs(url.query)):
            return self._json(403, {"error": "forbidden"})
        if url.path != "/api/action":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            message = json.loads(self.rfile.read(length) or b"{}")
            name, args = str(message["name"]), dict(message.get("args") or {})
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"error": "bad request"})
        asyncio.run_coroutine_threadsafe(self.bridge.controller.dispatch(name, args), self.bridge.loop)
        return self._json(202, {"ok": True})

    def _static(self, name: str):
        root = self.bridge.ui_dir.resolve()
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            return self._json(404, {"error": "not found"})
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "image/svg+xml"):
            content_type += "; charset=utf-8"
        return self._send(200, path.read_bytes(), content_type)
