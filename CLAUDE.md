# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PScan turns Marc's Android phone into a document scanner for his own Windows PC (personal use; no CEAT OCS or other
org branding). Two Python programs talk over the local network:

- **`pc/`**: `pscan_server`, a FastAPI server with a tray icon that starts with Windows. It processes page photos
  (OpenCV), OCRs them (Tesseract) and writes PDFs to `Scans/`.
- **`phone/`**: the `pscan` Android app (BeeWare Toga + Briefcase, Python on Android via Chaquopy). Its UI is an
  HTML page in a WebView, driven by a Python controller.

The user-facing setup and troubleshooting guide is `README.md`.

## Commands

Run everything from the repo root in PowerShell.
- `pc\.venv` has the server, test and lint packages and is also used to run the phone tests. Create it with
  `pc\scripts\setup.ps1`.
- `phone\.venv` only has Briefcase/Toga, for building the app. Create it with `phone\setup.ps1`
  (`phone\requirements-dev.txt`).

```powershell
pc\.venv\Scripts\python -m pytest pc\tests phone\tests          # all tests (~25 s)
pc\.venv\Scripts\python -m pytest pc\tests\test_api.py::test_full_scan_flow   # one test
pc\.venv\Scripts\python -m pytest phone\tests -k bridge          # by keyword
pc\.venv\Scripts\ruff check .                                     # lint (config: ruff.toml)
pc\.venv\Scripts\ruff format .                                    # format; CI-style check: ruff format --check .
```

- The OCR and orientation tests are skipped when Tesseract isn't installed (`C:\Program Files\Tesseract-OCR`).
- `phone\tests` start a real PScan server in-process on free ports, so they don't clash with the PScan instance that
  is normally already running on 8765.

Running things:

```powershell
cd pc; .venv\Scripts\python -m pscan_server --no-tray --host 127.0.0.1   # server in a console, this PC only
cd phone\tools; ..\..\pc\.venv\Scripts\python preview_ui.py               # phone UI in a desktop browser
cd phone; powershell -ExecutionPolicy Bypass -File .\release.ps1          # signed release APK -> phone\dist\PScan-<version>.apk
cd phone; powershell -ExecutionPolicy Bypass -File .\briefcase.ps1 run android -u   # debug build over USB
cd phone\icons; ..\..\pc\.venv\Scripts\python make_icons.py               # regenerate app icons
```

- **Server notes:**
  - `--host 127.0.0.1` avoids the Windows Firewall prompt during development.
  - If the autostarted server already holds port 8765, a second `python -m pscan_server` exits with "already
    running".
  - To restart the real server after server-code changes, stop its `pythonw` processes and relaunch the Start-menu
    `PScan.lnk` through `explorer.exe`. Processes started directly from Claude desktop's sandbox may not outlive it.
- **`preview_ui.py`:**
  - Runs the real `Controller` and `Bridge` with a fake camera (sample photos) and prints a URL.
  - It still needs a PC server to pair with: start a throwaway one on another port and use the manual-address field.
- **Always go through `briefcase.ps1`, never `briefcase` directly.** It sets `BRIEFCASE_HOME` to
  `C:\Users\Marc\dev\.briefcase` (two levels above `phone\`), where the JDK, Android SDK and `adb.exe`
  (`tools\android_sdk\platform-tools\`) live.
- **Versioning:** bump `version` in `phone\pyproject.toml`. `release.ps1` re-creates the Android project when its
  `versionName` differs, because Briefcase writes the version only at `create` time.
- **Signing key:**
  - `release.ps1` signs with `phone\signing\pscan-release.jks` (gitignored).
  - If the key is missing, the script stops (it only makes a new key with `-NewKey`). On another PC, copy
    `phone\signing\` over by hand.
  - Don't regenerate it: installed phones must uninstall the app to accept a new key, which also loses their pairing.

## Architecture

### Network protocol (`pc/pscan_server` ⇄ `phone/src/pscan`)

- **UDP 8766 discovery** (`discovery.py` on both sides):
  - The phone broadcasts `{"t":"pscan-discover"}`; the PC replies to the sender.
  - The PC also broadcasts a `pscan-here` beacon every 3 s to each adapter's directed broadcast address. This covers
    the phone-hotspot case.
  - The phone remembers each PC by `server_id` (`pc/data/server_id.txt`), so it can find the PC again after an IP
    change. Each PC must keep its own `pc/data`: copying it to another PC duplicates the identity.
- **Pairing:**
  - `POST /api/pair/start` makes a 6-digit code, shown as a Windows toast.
  - `POST /api/pair/finish` returns a bearer token. Only its SHA-256 is stored, in `pc/data/devices.json` (`auth.py`).
- **Scan flow** (all `/api/sessions/...`, bearer token required):
  - Create a session.
  - Upload each photo as a raw `image/jpeg` body (`?replace=<pid>` for a retake).
  - Fetch previews with `?mode=&paper=`, PATCH rotate/crop, reorder, delete.
  - `finish` builds the PDF.
- **Compatibility:** phones update separately from the PC, so keep API changes backward compatible (new params
  optional).

### PC server pipeline

`server.py` (routes) → `sessions.SessionStore` → `processing` → `pdf_builder` → `notify`.

- **Sessions** live on disk in `pc/data/sessions/<id>/`. They survive restarts and are cleaned up after 24 h.
  - Each page stores `<pid>.orig.jpg`, `<pid>.warp.jpg` and settings in `session.json`.
  - Rendering always starts from those files, so rotate, crop on/off, mode and paper changes are non-destructive.
- **Upload processing** (`add_page`):
  1. EXIF-upright load, capped at `max_long_edge`.
  2. `detect_page`: Canny-edge and Otsu-brightness candidate quads, sanity-checked.
  3. `warp_page`: recovers the page's true aspect ratio with the Zhang–He whiteboard method, then trims the border.
  4. Tesseract `--psm 0` auto-rotation.
- **Rendering for the PDF:**
  1. Rotate.
  2. `enhance(mode)`: background-division shadow removal for color/gray, adaptive threshold for bw.
  3. `finalize_page(paper)`. This snaps pages within 6 % of the paper's shape and pads anything else with white. It
     picks a whole-number DPI (JPEG stores DPI as an integer) so PDF pages are exactly A4/Letter/etc.
- **`pdf_builder`:**
  - Runs Tesseract per page in a thread pool and merges the pages with pypdf.
  - Falls back to img2pdf per page if OCR fails.
  - Writes the PDF atomically, as a `.partial` file followed by `os.replace`, and never overwrites (`name (2).pdf`).
- **`__main__.py`** runs uvicorn, discovery and session cleanup in threads, with the pystray tray icon on the main
  thread.
  - Under `pythonw`, `sys.stdout`/`stderr` are `None` and get replaced with devnull.
  - Logging goes to `pc/data/logs/pscan.log`.
  - Subprocesses use `CREATE_NO_WINDOW`.

### Phone app

```
WebView (ui/index.html + app.css + app.js)
   ⇅  HTTP on 127.0.0.1:<random port>, random key   (bridge.py, ThreadingHTTPServer)
Controller (controller.py): all app logic, on Toga's asyncio loop
   ⇅  client.py (stdlib urllib) / discovery.py (UDP)          → PC server
```

- **`app.py`** is a thin Toga shell. It creates the `Controller`, starts the `Bridge` in `on_running`, and points a
  full-screen `toga.WebView` at `bridge.url`.
- **`android_ui.py`** handles the Android side:
  - Hides the action bar and goes edge-to-edge.
  - Reports the status-bar, navigation-bar and keyboard insets through `Controller.set_insets`; the page uses them as
    `--safe-top`/`--safe-bottom`.
  - Sets the system-bar icon colors.
  - It only imports on Android.
- **State flows one way:**
  - `Controller` mutates its state, then calls `notify()`, which builds a versioned JSON `snapshot()`.
  - `app.js` long-polls `GET /api/state?since=<v>` and re-renders from the snapshot.
  - User input goes back as `POST /api/action {name, args}`, which `Controller.dispatch` runs on the event loop.
  - Keep business logic in Python. The JS only renders and confirms.
- **Adding a feature:**
  1. Write an async method on `Controller`.
  2. Register it in `dispatch`'s table.
  3. Expose any new state in `snapshot()`, which must stay JSON-serializable.
  4. Call `act("<name>", {...})` from `app.js`.
- **Uploads:**
  - A single `upload_worker` uploads pages in order and retries until each succeeds.
  - Photos not yet on the PC are kept in `app.paths.data/photos` and listed in `settings.json` (`state.py`), so they
    survive the app being killed while the camera is open.
  - `session_lock` prevents two sessions being created at once.
  - `restore_session` reloads an unfinished scan after restart.
- **Several PCs** (e.g. home laptop and office desktop):
  - `AppState.servers` holds every paired PC; `active_id` says which one gets scans. `state.server` is the active
    one. Settings from 0.2.x (a single `server`) are migrated on load.
  - `try_connect`: if the active PC doesn't answer at its last address, it runs discovery, updates every paired PC's
    address, and auto-switches (`_switch_to`) to another paired PC on the network. It only does this when no page of
    the current scan is on the old PC (`_pages_on_pc()`); otherwise it shows "X is here" in the status.
  - Switching keeps photos still on the phone (`_keep_only_photos`); pages that live only on the old PC and its
    session are dropped. That's why `app.js` asks for confirmation before a manual switch or adding a PC.
  - Actions: `use_pc`, `add_pc`, `connect_back`, `forget_pc`.
  - `Controller(find_pcs=...)` injects discovery so `phone/tests/test_multi_pc.py` can simulate which PCs are nearby.
- **`camera.py`:**
  - On Android it fires `ACTION_IMAGE_CAPTURE` through the app's FileProvider (`{app_id}.fileprovider`, cache
    `shared/`). It moves the original JPEG into app storage without decoding it, which preserves EXIF and full
    resolution.
  - On desktop it opens a file picker.
- **Phone code must stay pure Python** (stdlib + Toga), with no binary wheels.
  - Plain HTTP to the PC works because Python sockets bypass Android's cleartext-traffic policy.
  - The generated network config only whitelists 127.0.0.1/localhost for the WebView.

### Things that must stay in sync

- **Paper sizes:**
  - `pc/pscan_server/processing.py` `PAPERS`/`PAPER_NAMES`
  - `phone/src/pscan/state.py` `PAPERS` (labels)
  - `PAPER_RATIOS` in `ui/app.js`
  - The default is `A4` (`pc/config.toml` `paper`).
- **Modes** (`color`/`gray`/`bw`): `pc/pscan_server/config.py` `MODES` and `phone/src/pscan/state.py` `MODES`.
- **Theme colors** (maroon `#8d1436`, green `#00563F`, gold `#FFB61C`):
  - CSS variables in `ui/app.css`
  - `pc/pscan_server/icon.py` (launcher and tray icons)
  - Icons are hand-drawn inline SVGs in `ICONS` in `app.js`.
- **About modal:** content lives in `ui/index.html`; its footer year comes from `BUILD_YEAR` in `controller.py`.

## Environment notes

- **Platform:** Windows 11 with Python 3.14 (the code targets 3.12+). On Android, Briefcase/Chaquopy also uses Python
  3.14; arm64 + x86_64 builds only.
- **Phone:** Oppo Reno 13F (CPH2701, Android 16, ColorOS).
  - `adb install` can fail with `INSTALL_FAILED_VERIFICATION_FAILURE` unless "Install via USB" is on, and Play
    Protect may block sideloaded APKs. Prefer the signed release APK from `release.ps1`.
  - To check UI changes on the device: `adb shell screencap -p /sdcard/x.png` then `adb pull`.
- **Claude desktop sandbox:** writes to `%LOCALAPPDATA%` from Claude desktop land in its MSIX sandbox. That's why
  venvs, runtime data (`pc/data`) and the Android tools all live in normal folders instead.
- **OneDrive:** the user's Desktop and Documents are synced by OneDrive. Keep the repo and `Scans/` out of OneDrive.
  Finished PDFs must never be saved there.
- **Test helpers:** they live in `pc/tests/pscan_samples.py` and `phone/tests/pscan_testing.py`, and each `conftest.py`
  only re-exports fixtures. Importing helpers `from conftest` breaks when both test folders run in one pytest session.
