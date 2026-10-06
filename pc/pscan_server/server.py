"""HTTP API the phone app talks to."""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .auth import DeviceStore, Pairing, PairingError
from .config import MODES, Config
from .notify import Notifier
from .pdf_builder import build_pdf
from .processing import PAPER_NAMES, ImageDecodeError
from .sessions import NotFound, SessionStore

log = logging.getLogger(__name__)

MAX_UPLOAD = 40 * 1024 * 1024  # a 50 MP phone JPEG is ~15-25 MB


class PairStart(BaseModel):
    device_name: str = Field("Phone", max_length=100)


class PairFinish(BaseModel):
    pair_id: str = Field(max_length=64)
    code: str = Field(max_length=20)


class PageUpdate(BaseModel):
    rotate: int | None = None
    crop: bool | None = None


class PageOrder(BaseModel):
    page_ids: list[str]


class FinishRequest(BaseModel):
    name: str | None = Field(None, max_length=200)
    mode: str | None = None
    paper: str | None = None
    ocr: bool | None = None


def _check_paper(paper: str) -> None:
    if paper not in PAPER_NAMES:
        raise HTTPException(400, f"Paper must be one of {', '.join(PAPER_NAMES)}.")


def create_app(config: Config, notifier: Notifier | None = None) -> FastAPI:
    config.ensure_dirs()
    notifier = notifier or Notifier()
    devices = DeviceStore(config.devices_path)
    pairing = Pairing(devices, on_code=notifier.pairing_code)
    store = SessionStore(config)
    finishing: set[str] = set()
    finishing_lock = threading.Lock()

    app = FastAPI(title="PScan", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config
    app.state.store = store
    app.state.devices = devices
    app.state.pairing = pairing
    app.state.notifier = notifier

    @app.exception_handler(NotFound)
    async def _not_found(request, exc):
        return JSONResponse({"detail": "That scan or page no longer exists on the PC."}, status_code=404)

    @app.exception_handler(ImageDecodeError)
    async def _bad_image(request, exc):
        return JSONResponse({"detail": "The PC could not read that photo."}, status_code=400)

    def require_device(authorization: str | None = Header(default=None)) -> dict:
        token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else None
        device = devices.verify(token)
        if device is None:
            raise HTTPException(401, "This phone is not paired with this PC.")
        return device

    # ------------------------------------------------------------ public routes

    @app.get("/api/health")
    def health():
        return {
            "app": "pscan",
            "name": config.server_name,
            "server_id": config.server_id,
            "version": __version__,
            "ocr_available": config.find_tesseract() is not None,
            "default_mode": config.default_mode,
            "papers": list(PAPER_NAMES),
            "default_paper": config.paper,
            "ocr_default": config.ocr,
        }

    @app.post("/api/pair/start")
    def pair_start(body: PairStart):
        try:
            return {"pair_id": pairing.start(body.device_name)}
        except PairingError as exc:
            raise HTTPException(429, str(exc)) from exc

    @app.post("/api/pair/finish")
    def pair_finish(body: PairFinish):
        try:
            token = pairing.finish(body.pair_id, body.code)
        except PairingError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"token": token, "server_id": config.server_id, "name": config.server_name}

    # ------------------------------------------------------- paired-only routes

    @app.get("/api/me")
    def me(device: dict = Depends(require_device)):
        return {"device": device["name"], "server_name": config.server_name}

    @app.post("/api/sessions")
    def create_session(device: dict = Depends(require_device)):
        return store.public(store.create())

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str, device: dict = Depends(require_device)):
        return store.public(store.get(sid))

    @app.delete("/api/sessions/{sid}")
    def delete_session(sid: str, device: dict = Depends(require_device)):
        store.delete(sid)
        return {"ok": True}

    @app.post("/api/sessions/{sid}/pages")
    async def upload_page(
        sid: str, request: Request, replace: str | None = None, device: dict = Depends(require_device)
    ):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_UPLOAD:
            raise HTTPException(413, "That photo is too large.")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD:
                raise HTTPException(413, "That photo is too large.")
            chunks.append(chunk)
        if not size:
            raise HTTPException(400, "No photo was received.")
        page = await run_in_threadpool(store.add_page, sid, b"".join(chunks), replace)
        return store.public_page(page)

    @app.get("/api/sessions/{sid}/pages/{pid}/preview.jpg")
    def preview(
        sid: str,
        pid: str,
        mode: str | None = None,
        paper: str | None = None,
        device: dict = Depends(require_device),
    ):
        mode = mode or config.default_mode
        paper = paper or config.paper
        if mode not in MODES:
            raise HTTPException(400, f"Mode must be one of {', '.join(MODES)}.")
        _check_paper(paper)
        data = store.render_preview(sid, pid, mode, paper)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.patch("/api/sessions/{sid}/pages/{pid}")
    def update_page(sid: str, pid: str, body: PageUpdate, device: dict = Depends(require_device)):
        if body.rotate is not None and body.rotate % 90:
            raise HTTPException(400, "Rotation must be a multiple of 90 degrees.")
        return store.public_page(store.update_page(sid, pid, rotate=body.rotate, crop=body.crop))

    @app.delete("/api/sessions/{sid}/pages/{pid}")
    def delete_page(sid: str, pid: str, device: dict = Depends(require_device)):
        store.delete_page(sid, pid)
        return store.public(store.get(sid))

    @app.put("/api/sessions/{sid}/order")
    def reorder(sid: str, body: PageOrder, device: dict = Depends(require_device)):
        try:
            return store.public(store.reorder(sid, body.page_ids))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/sessions/{sid}/finish")
    def finish(sid: str, body: FinishRequest, device: dict = Depends(require_device)):
        mode = body.mode or config.default_mode
        paper = body.paper or config.paper
        if mode not in MODES:
            raise HTTPException(400, f"Mode must be one of {', '.join(MODES)}.")
        _check_paper(paper)
        ocr = config.ocr if body.ocr is None else body.ocr
        with finishing_lock:
            if sid in finishing:
                raise HTTPException(409, "This scan is already being saved.")
            finishing.add(sid)
        try:
            if not store.get(sid)["pages"]:
                raise HTTPException(400, "Add at least one page first.")
            with tempfile.TemporaryDirectory(prefix="pscan-render-") as tmp:
                pages = store.render_final(sid, mode, Path(tmp), paper)
                result = build_pdf(
                    pages,
                    config.output_dir,
                    name=body.name,
                    ocr=ocr,
                    tesseract=config.find_tesseract() if ocr else None,
                    lang=config.ocr_lang,
                )
            store.delete(sid)
        finally:
            with finishing_lock:
                finishing.discard(sid)
        notifier.scan_saved(result.path, result.pages, result.ocr_applied, result.ocr_error)
        log.info("Device %r saved %s", device["name"], result.path.name)
        return {
            "filename": result.path.name,
            "folder": str(result.path.parent),
            "pages": result.pages,
            "paper": paper,
            "ocr_applied": result.ocr_applied,
            "ocr_error": result.ocr_error,
        }

    return app
