"""PScan phone app: photograph document pages; your PC turns them into a PDF.

The screen is an HTML page (``ui/``) shown full-screen in a WebView. The page talks to
the Python ``Controller`` through a small web server bound to 127.0.0.1 (``bridge``).
"""

from __future__ import annotations

import asyncio
import logging
import platform

import toga

from . import camera
from .bridge import Bridge
from .controller import APP_VERSION, Controller

log = logging.getLogger("pscan")


def device_name(app: toga.App) -> str:
    if toga.platform.current_platform == "android":
        try:
            from android.provider import Settings

            name = Settings.Global.getString(app._impl.native.getContentResolver(), "device_name")
            if name:
                return str(name)
        except Exception:
            pass
        try:
            from android.os import Build

            return f"{Build.MANUFACTURER} {Build.MODEL}".strip()
        except Exception:
            pass
    return platform.node() or "Phone"


class PScanApp(toga.App):
    def startup(self):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        self.controller = Controller(
            data_dir=self.paths.data,
            take_photo=lambda: camera.take_photo(self),
            device_name=device_name(self),
            app_version=self.version or APP_VERSION,  # from pyproject.toml via the app's metadata
        )
        self.webview = toga.WebView(flex=1)
        self.main_window = toga.MainWindow(title="PScan")
        self.main_window.content = self.webview
        if toga.platform.current_platform == "android":
            from . import android_ui

            android_ui.setup(self, self.webview, self.controller)
        self.main_window.show()

    async def on_running(self):
        self.bridge = Bridge(self.controller, asyncio.get_running_loop())
        self.bridge.start()
        self.controller.start()
        self.webview.url = self.bridge.url


def main():
    return PScanApp("PScan", "com.marcdavid.pscan")
