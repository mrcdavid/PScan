r"""Shared test helpers: a real PScan PC server running in this process.

These tests need the PC server's packages; run them with the PC venv from the project root:
    pc\.venv\Scripts\python -m pytest phone\tests
"""

import asyncio
import contextlib
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "phone" / "src"))
sys.path.insert(0, str(ROOT / "pc"))

pytest.importorskip("fastapi", reason="needs the PC server's packages (use pc\\.venv)")
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import uvicorn  # noqa: E402

from pscan_server.config import Config  # noqa: E402
from pscan_server.discovery import DiscoveryService  # noqa: E402
from pscan_server.notify import NullNotifier  # noqa: E402
from pscan_server.server import create_app  # noqa: E402


def free_port(kind=socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def photo_bytes() -> bytes:
    img = np.full((900, 1200, 3), 50, np.uint8)
    quad = np.array([[350, 80], [880, 120], [900, 820], [300, 790]], np.int32)
    cv2.fillPoly(img, [quad], (240, 240, 240))
    for y in range(200, 700, 60):
        cv2.line(img, (400, y), (800, y + 5), (30, 30, 30), 4)
    return cv2.imencode(".jpg", img)[1].tobytes()


@contextlib.contextmanager
def running_server(tmp: Path, name: str):
    """A PScan PC server (HTTP + discovery) on free localhost ports; yields (app, config)."""
    config = Config(
        server_name=name,
        port=free_port(),
        discovery_port=free_port(socket.SOCK_DGRAM),
        output_dir=tmp / "Scans",
        default_mode="color",
        ocr=False,
        ocr_lang="eng",
        tesseract_path="",
        max_long_edge=3000,
        jpeg_quality=85,
        data_dir=tmp / "data",
    )
    app = create_app(config, notifier=NullNotifier())
    http = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config.port, log_config=None))
    thread = threading.Thread(target=http.run, daemon=True)
    thread.start()
    discovery = DiscoveryService(
        {"id": config.server_id, "name": config.server_name, "port": config.port},
        port=config.discovery_port,
        host="127.0.0.1",
        beacon_interval=0,
    )
    discovery.start()
    deadline = time.time() + 10
    while not http.started and time.time() < deadline:
        time.sleep(0.05)
    assert http.started and discovery.ready.wait(5)
    try:
        yield app, config
    finally:
        discovery.stop()
        http.should_exit = True
        thread.join(5)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with running_server(tmp_path_factory.mktemp("pscan"), "TEST-PC") as handle:
        yield handle


@pytest.fixture(scope="module")
def second_server(tmp_path_factory):
    """Another PC, e.g. the office desktop."""
    with running_server(tmp_path_factory.mktemp("pscan2"), "OFFICE-PC") as handle:
        yield handle


async def wait_until(predicate, timeout=30.0):
    for _ in range(int(timeout * 20)):
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("timed out")


def make_controller(tmp_path, **kwargs):
    """A phone-app Controller whose camera returns sample page photos."""
    from pscan.controller import Controller

    async def take_photo():
        path = tmp_path / f"{uuid.uuid4().hex}.jpg"
        path.write_bytes(photo_bytes())
        return path

    return Controller(data_dir=tmp_path / "data", take_photo=take_photo, device_name="Test phone", **kwargs)
