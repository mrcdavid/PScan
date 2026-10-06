"""Get a page photo as a JPEG file.

On Android this opens the phone's own camera app and keeps the original JPEG it writes
(full quality, EXIF orientation intact, never decoded on the phone). On a desktop
(``briefcase dev`` on Windows, for testing) it opens a file picker instead.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path

import toga

log = logging.getLogger(__name__)


def photos_dir(app: toga.App) -> Path:
    """Where taken photos wait until they're on the PC (survives app restarts)."""
    path = app.paths.data / "photos"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def take_photo(app: toga.App) -> Path | None:
    if toga.platform.current_platform == "android":
        return await _android_camera(app)
    return await _pick_file(app)


async def _android_camera(app: toga.App) -> Path | None:
    from android.content import Intent
    from android.provider import MediaStore
    from androidx.core.content import FileProvider
    from java.io import File

    if not app.camera.has_permission and not await app.camera.request_permission():
        raise PermissionError("PScan needs camera permission to photograph pages.")

    context = app._impl.native.getApplicationContext()
    # The cache "shared" folder is the one exposed through the app's FileProvider.
    shared = File(context.getCacheDir(), "shared")
    if not shared.exists():
        shared.mkdirs()
    photo_file = File.createTempFile("page", ".jpg", shared)
    photo_uri = FileProvider.getUriForFile(context, f"{app.app_id}.fileprovider", photo_file)

    done = asyncio.get_running_loop().create_future()

    def on_complete(result_code, data):
        if not done.done():
            done.set_result(result_code)

    intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
    intent.putExtra(MediaStore.EXTRA_OUTPUT, photo_uri)
    intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION)
    app._impl.start_activity(intent, on_complete=on_complete)
    result_code = await done

    taken = Path(str(photo_file.getAbsolutePath()))
    # Activity.RESULT_OK is -1; RESULT_CANCELED is 0.
    if not result_code or not taken.exists() or taken.stat().st_size == 0:
        taken.unlink(missing_ok=True)
        return None
    # Move it out of the cache so Android can't clear it before it's uploaded.
    kept = photos_dir(app) / f"{uuid.uuid4().hex}.jpg"
    shutil.move(str(taken), kept)
    return kept


async def _pick_file(app: toga.App) -> Path | None:
    chosen = await app.main_window.dialog(
        toga.OpenFileDialog("Choose a photo of a page", file_types=["jpg", "jpeg", "png"])
    )
    if not chosen:
        return None
    kept = photos_dir(app) / f"{uuid.uuid4().hex}{Path(chosen).suffix.lower()}"
    shutil.copyfile(chosen, kept)
    return kept
