"""Start the installed PScan.exe when the user logs in (HKCU Run value).

Only used by the packaged app. From source, the repo's install_autostart.ps1 shortcut
does the same job, so these functions no-op unless running frozen.
"""

from __future__ import annotations

import logging
import sys

from .config import is_frozen

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE = "PScan"


def _exe_command() -> str:
    return f'"{sys.executable}"'


def is_enabled() -> bool:
    if not is_frozen():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        log.exception("Could not read autostart setting")
        return False


def set_enabled(enabled: bool) -> None:
    """Add or remove the login-start entry for the current user. No-op from source."""
    if not is_frozen():
        return
    import winreg

    try:
        if enabled:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.SetValueEx(key, _VALUE, 0, winreg.REG_SZ, _exe_command())
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, _VALUE)
                except FileNotFoundError:
                    pass
    except OSError:
        log.exception("Could not change autostart setting")


def ensure_default() -> None:
    """On the installed app's first run, turn autostart on if it was never set."""
    if not is_frozen():
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE)
            return  # already set (on or previously removed is respected only if present)
    except FileNotFoundError:
        pass
    except OSError:
        return
    # Mark that we've applied the default so we don't re-enable after the user turns it off.
    from .config import home_dir

    marker = home_dir() / "data" / ".autostart_applied"
    if marker.exists():
        return
    set_enabled(True)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass
