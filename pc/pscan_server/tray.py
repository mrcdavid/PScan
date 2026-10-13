"""System-tray icon with the few things you need when PScan runs in the background."""

from __future__ import annotations

import ctypes
import logging
import os
import socket
import subprocess
import threading

import pystray

from . import autostart
from .auth import DeviceStore, Pairing
from .config import Config, installed_mode
from .icon import draw_icon

log = logging.getLogger(__name__)

MB_YESNO = 0x04
MB_ICONINFORMATION = 0x40
MB_ICONQUESTION = 0x20
MB_SETFOREGROUND = 0x10000
IDYES = 6
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _pick_folder(initial: str) -> str | None:
    """Show a native Choose-Folder dialog (via PowerShell) and return the chosen path."""
    # Single-quoted PowerShell string: backslashes are literal, quotes are doubled.
    safe_initial = initial.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description = 'Choose where PScan saves PDFs';"
        "$d.SelectedPath = '" + safe_initial + "';"
        "if ($d.ShowDialog() -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.exception("Folder picker failed")
        return None
    chosen = proc.stdout.strip()
    return chosen or None


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

    def change_folder(icon, item):
        def ask():
            chosen = _pick_folder(str(config.output_dir))
            if chosen:
                try:
                    config.save_output_dir(chosen)
                    _message_box(f"PDFs will now be saved in:\n\n{chosen}")
                except OSError:
                    log.exception("Could not change the Scans folder")
                    _message_box("Could not use that folder. Pick a different one.")

        _in_background(ask)

    def open_logs(icon, item):
        config.logs_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(config.logs_dir)

    def toggle_autostart(icon, item):
        autostart.set_enabled(not autostart.is_enabled())

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

    items = [
        pystray.MenuItem(lambda item: f"PScan on {config.server_name}", None, enabled=False),
        pystray.MenuItem(lambda item: f"IP {primary_ip()} · port {config.port}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Scans folder", open_folder, default=True),
        pystray.MenuItem("Change Scans folder…", change_folder),
        pystray.MenuItem("Show pairing code", show_code),
        pystray.MenuItem("Forget paired phones…", forget),
        pystray.MenuItem("Open log folder", open_logs),
    ]
    if installed_mode():  # from source, install_autostart.ps1 handles start-with-Windows
        items.append(
            pystray.MenuItem("Start with Windows", toggle_autostart, checked=lambda item: autostart.is_enabled())
        )
    items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Quit PScan", quit_app)]
    menu = pystray.Menu(*items)
    icon = pystray.Icon("PScan", draw_icon(64), "PScan – phone scanner", menu)
    icon.run()
