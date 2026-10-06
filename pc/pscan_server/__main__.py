"""Start PScan: HTTP API + network discovery + tray icon.

python -m pscan_server            # with tray icon (what autostart uses, via pythonw)
python -m pscan_server --no-tray  # in a console window, Ctrl+C to stop
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time

import uvicorn

from . import __version__
from .config import load_config
from .discovery import DiscoveryService
from .notify import Notifier
from .server import create_app

log = logging.getLogger("pscan_server")


def _fix_std_streams() -> bool:
    """pythonw.exe has no console, so sys.stdout/stderr are None. Returns True if console."""
    has_console = sys.stderr is not None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - stays open for the process
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - stays open for the process
    return has_console


def _setup_logging(log_dir, console: bool) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(log_dir / "pscan.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    ]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _port_in_use(port: int, host: str) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind((host, port))
        except OSError:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pscan_server", description="PScan PC server")
    parser.add_argument("--no-tray", action="store_true", help="run in this console without a tray icon")
    parser.add_argument("--host", default="0.0.0.0", help="address to listen on (127.0.0.1 = this PC only)")
    args = parser.parse_args(argv)

    console = _fix_std_streams()
    config = load_config()
    config.ensure_dirs()
    _setup_logging(config.logs_dir, console)
    notifier = Notifier()

    if _port_in_use(config.port, args.host):
        log.error("Port %d is already in use; is PScan already running?", config.port)
        notifier.message(
            "PScan is already running",
            f"Port {config.port} is in use. Look for the PScan icon next to the clock.",
        )
        return 1

    app = create_app(config, notifier)
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=config.port, log_config=None, access_log=False))
    http_thread = threading.Thread(target=server.run, name="pscan-http", daemon=True)
    http_thread.start()
    for _ in range(100):  # wait up to 10 s for the server to come up
        if server.started or not http_thread.is_alive():
            break
        time.sleep(0.1)
    if not server.started:
        log.error("The HTTP server failed to start")
        notifier.message("PScan could not start", "See pc\\data\\logs\\pscan.log for details.")
        return 1

    discovery = DiscoveryService(
        {"id": config.server_id, "name": config.server_name, "port": config.port},
        port=config.discovery_port,
        host="" if args.host == "0.0.0.0" else args.host,
    )
    discovery.start()

    stop = threading.Event()

    def housekeeping():
        while True:
            try:
                app.state.store.cleanup()
            except Exception:
                log.exception("Session cleanup failed")
            if stop.wait(3600):
                return

    threading.Thread(target=housekeeping, name="pscan-cleanup", daemon=True).start()

    def shutdown():
        stop.set()
        discovery.stop()
        server.should_exit = True

    tesseract = config.find_tesseract()
    log.info(
        "PScan %s ready as %r on port %d; PDFs go to %s; OCR: %s",
        __version__,
        config.server_name,
        config.port,
        config.output_dir,
        tesseract or "not installed",
    )

    if args.no_tray:
        print(f"PScan is running as {config.server_name!r}. Press Ctrl+C to stop.")
        try:
            while http_thread.is_alive():
                http_thread.join(0.5)
        except KeyboardInterrupt:
            pass
        shutdown()
    else:
        from .tray import run_tray

        run_tray(config, app.state.pairing, app.state.devices, on_quit=shutdown)
        shutdown()

    http_thread.join(timeout=5)
    log.info("PScan stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
