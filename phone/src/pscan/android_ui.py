"""Android-only touches: full-screen themed UI that respects the status bar, gesture bar
and keyboard (Android 15+ always draws apps edge-to-edge)."""

from __future__ import annotations

import logging

from android.graphics import Color
from android.os import Build
from android.view import View, WindowInsets, WindowInsetsController
from androidx.core.view import WindowCompat
from java import dynamic_proxy

log = logging.getLogger("pscan.android")

BACKGROUND = "#F4F1F2"  # matches the page background, shown while the page loads


class InsetsListener(dynamic_proxy(View.OnApplyWindowInsetsListener)):
    """Passes the space taken by the system bars and keyboard to the page (as CSS px)."""

    def __init__(self, controller, density: float):
        super().__init__()
        self.controller = controller
        self.density = density

    def onApplyWindowInsets(self, view, insets):
        try:
            if Build.VERSION.SDK_INT >= 30:
                bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout())
                ime = insets.getInsets(WindowInsets.Type.ime())
                top, bottom = bars.top, max(bars.bottom, ime.bottom)
            else:
                top, bottom = insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetBottom()
            self.controller.set_insets(top / self.density, bottom / self.density)
        except Exception:
            log.exception("Could not read window insets")
        return view.onApplyWindowInsets(insets)


def setup(app, webview, controller) -> None:
    activity = app._impl.native
    window = activity.getWindow()

    # Our page draws its own themed header, so drop the default action bar.
    action_bar = activity.getSupportActionBar()
    if action_bar is not None:
        action_bar.hide()

    # Draw behind the status and navigation bars on every Android version; the page
    # pads itself using the insets reported below.
    WindowCompat.setDecorFitsSystemWindows(window, False)
    if Build.VERSION.SDK_INT < 35:
        window.setStatusBarColor(Color.TRANSPARENT)
        window.setNavigationBarColor(Color.TRANSPARENT)
    # White status-bar icons over the maroon header; dark navigation icons over the white bottom bar.
    if Build.VERSION.SDK_INT >= 30:
        window.getInsetsController().setSystemBarsAppearance(
            WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
            WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
            | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
        )
    elif Build.VERSION.SDK_INT >= 26:
        window.getDecorView().setSystemUiVisibility(
            View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        )

    native = webview._impl.native
    native.setBackgroundColor(Color.parseColor(BACKGROUND))
    native.setOverScrollMode(View.OVER_SCROLL_NEVER)
    native.setVerticalScrollBarEnabled(False)
    native.setHorizontalScrollBarEnabled(False)
    native.setHapticFeedbackEnabled(False)
    settings = native.getSettings()
    settings.setSupportZoom(False)
    settings.setBuiltInZoomControls(False)
    settings.setDisplayZoomControls(False)
    # Respect the phone's text-size setting, but cap it so the layout stays usable.
    settings.setTextZoom(min(settings.getTextZoom(), 115))

    density = activity.getResources().getDisplayMetrics().density
    native.setOnApplyWindowInsetsListener(InsetsListener(controller, density))
    native.requestApplyInsets()
