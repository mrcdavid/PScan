"""Talks to the PScan server on the PC (plain HTTP on the local network, stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_PORT = 8765

# Ignore any system proxy: the PC is on the local network.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ConnectionFailed(ApiError):
    """The PC could not be reached at all."""


class Unauthorized(ApiError):
    """The PC doesn't recognise this phone (not paired, or the pairing was forgotten)."""


class NotFound(ApiError):
    """The scan or page no longer exists on the PC."""


class PScanClient:
    def __init__(self, host: str, port: int = DEFAULT_PORT, token: str | None = None, timeout: float = 15):
        self.host = host
        self.port = port
        self.token = token
        self.timeout = timeout

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body=None,
        data: bytes | None = None,
        content_type: str | None = None,
        params: dict | None = None,
        timeout: float | None = None,
    ) -> bytes:
        url = self.base_url + path
        if params:
            query = {k: v for k, v in params.items() if v is not None}
            if query:
                url += "?" + urllib.parse.urlencode(query)
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if json_body is not None:
            data = json.dumps(json_body).encode()
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with _opener.open(request, timeout=timeout or self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("detail")
            except Exception:
                detail = None
            message = detail if isinstance(detail, str) else f"The PC answered with error {exc.code}."
            error_type = {401: Unauthorized, 404: NotFound}.get(exc.code, ApiError)
            raise error_type(message, exc.code) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise ConnectionFailed(f"Can't reach the PC at {self.host}.") from exc

    def _json(self, method: str, path: str, **kwargs) -> dict:
        return json.loads(self._request(method, path, **kwargs) or b"{}")

    # ---------------------------------------------------------------- pairing

    def health(self, timeout: float | None = None) -> dict:
        return self._json("GET", "/api/health", timeout=timeout)

    def pair_start(self, device_name: str) -> str:
        return self._json("POST", "/api/pair/start", json_body={"device_name": device_name})["pair_id"]

    def pair_finish(self, pair_id: str, code: str) -> dict:
        return self._json("POST", "/api/pair/finish", json_body={"pair_id": pair_id, "code": code})

    def me(self) -> dict:
        return self._json("GET", "/api/me")

    # --------------------------------------------------------------- scanning

    def create_session(self) -> dict:
        return self._json("POST", "/api/sessions")

    def get_session(self, sid: str) -> dict:
        return self._json("GET", f"/api/sessions/{sid}")

    def delete_session(self, sid: str) -> None:
        self._json("DELETE", f"/api/sessions/{sid}")

    def upload_page(self, sid: str, photo: bytes | Path, replace: str | None = None) -> dict:
        data = photo.read_bytes() if isinstance(photo, Path) else photo
        return self._json(
            "POST",
            f"/api/sessions/{sid}/pages",
            data=data,
            content_type="image/jpeg",
            params={"replace": replace},
            timeout=180,  # big photo over slow Wi-Fi + processing on the PC
        )

    def preview(self, sid: str, pid: str, mode: str, paper: str = "A4") -> bytes:
        return self._request(
            "GET", f"/api/sessions/{sid}/pages/{pid}/preview.jpg", params={"mode": mode, "paper": paper}
        )

    def update_page(self, sid: str, pid: str, rotate: int | None = None, crop: bool | None = None) -> dict:
        body = {k: v for k, v in {"rotate": rotate, "crop": crop}.items() if v is not None}
        return self._json("PATCH", f"/api/sessions/{sid}/pages/{pid}", json_body=body)

    def delete_page(self, sid: str, pid: str) -> dict:
        return self._json("DELETE", f"/api/sessions/{sid}/pages/{pid}")

    def reorder(self, sid: str, page_ids: list[str]) -> dict:
        return self._json("PUT", f"/api/sessions/{sid}/order", json_body={"page_ids": page_ids})

    def finish(self, sid: str, name: str | None, mode: str, ocr: bool, paper: str = "A4") -> dict:
        return self._json(
            "POST",
            f"/api/sessions/{sid}/finish",
            json_body={"name": name or None, "mode": mode, "paper": paper, "ocr": ocr},
            timeout=900,  # OCR of many pages can take a while
        )
