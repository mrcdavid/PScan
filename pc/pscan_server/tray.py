"""System-tray icon with the few things you need when PScan runs in the background."""

from __future__ import annotations

import ctypes
import logging
import os
import socket
import threading

import pystray

from .auth import DeviceStore, Pairing
from .config import Config
from .icon import draw_icon

log = logging.getLogger(__name__)

MB_YESNO = 0x04
MB_ICONINFORMATION = 0x40
MB_ICONQUESTION = 0x20
MB_SETFOREGROUND = 0x10000
IDYES = 6


def primary_ip() -> str:
    """The IP address other devices on the network use to reach this PC."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the route
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _message_box(text: str, flags: int = MB_ICONINFORMATION) -> int:
    return ctypes.windll.user32.MessageBoxW(0, text, "PScan", flags | MB_SETFOREGROUND)


def _in_background(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def run_tray(config: Config, pairing: Pairing, devices: DeviceStore, on_quit) -> None:
    """Show the tray icon; blocks until the user chooses Quit."""

    def open_folder(icon, item):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(config.output_dir)

    def show_code(icon, item):
        current = pairing.current_code()
        if current:
            code, name = current
            text = f"Pairing code for {name}:\n\n        {code[:3]} {code[3:]}\n\nType it into the PScan app."
        else:
            text = (
                "No phone is waiting to pair.\n\n"
                "Open PScan on your phone and tap this PC's name; the code will appear here "
                "and as a notification."
            )
        _in_background(lambda: _message_box(text))

    def forget(icon, item):
        def ask():
            count = len(devices.list())
            if not count:
                _message_box("No phones are paired with this PC.")
                return
            answer = _message_box(
                f"Forget {count} paired phone(s)?\n\nThey will need a new pairing code to send scans again.",
                MB_YESNO | MB_ICONQUESTION,
            )
            if answer == IDYES:
                devices.forget_all()

        _in_background(ask)

    def quit_app(icon, item):
        log.info("Quit from tray")
        on_quit()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: f"PScan on {config.server_name}", None, enabled=False),
        pystray.MenuItem(lambda item: f"IP {primary_ip()} · port {config.port}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Scans folder", open_folder, default=True),
        pystray.MenuItem("Show pairing code", show_code),
        pystray.MenuItem("Forget paired phones…", forget),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit PScan", quit_app),
    )
    icon = pystray.Icon("PScan", draw_icon(64), "PScan – phone scanner", menu)
    icon.run()
