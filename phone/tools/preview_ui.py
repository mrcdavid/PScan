"""Preview the phone UI in a desktop browser, without building the APK.

Runs the app's Controller and Bridge on this PC with a fake camera that returns sample
page photos. Start the PC server first (or pass --server-port for a test server), then:

    ..\\..\\pc\\.venv\\Scripts\\python preview_ui.py

and open the printed URL (use the browser's phone/responsive view).
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE.parents[1] / "pc" / "tests"))

from pscan.bridge import Bridge  # noqa: E402
from pscan.controller import Controller  # noqa: E402


def sample_photos(folder: Path) -> list[Path]:
    """A few fake phone photos of pages (made with the PC tests' generator)."""
    import cv2

    from pscan_samples import camera_corners, make_photo

    folder.mkdir(parents=True, exist_ok=True)
    poses = [
        dict(rx=20, ry=10, rz=5),
        dict(rx=-15, ry=20, rz=-8),
        dict(rx=30, ry=-12, rz=3),
        dict(rx=5, ry=5, rz=90, distance=22),
    ]
    paths = []
    for i, pose in enumerate(poses):
        path = folder / f"sample-{i}.jpg"
        if not path.exists():
            photo, _ = make_photo(camera_corners(**pose), shadow=i == 1, seed=i)
            cv2.imwrite(str(path), photo)
        paths.append(path)
    return paths


async def main(args) -> None:
    data = Path(args.data or tempfile.mkdtemp(prefix="pscan-preview-"))
    samples = itertools.cycle(sample_photos(data / "samples"))

    async def take_photo():
        await asyncio.sleep(0.4)  # the camera app opening
        dst = data / "photos" / f"{uuid.uuid4().hex}.jpg"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(next(samples), dst)
        return dst

    controller = Controller(data_dir=data, take_photo=take_photo, device_name="Preview phone")
    controller.set_insets(args.inset_top, args.inset_bottom)
    bridge = Bridge(controller, asyncio.get_running_loop())
    bridge.start()
    controller.start()
    print("PScan UI preview:", bridge.url, flush=True)
    print("Settings/photos in", data, flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", help="folder for settings and photos (default: a new temp folder)")
    parser.add_argument("--inset-top", type=float, default=32, help="pretend status-bar height (CSS px)")
    parser.add_argument("--inset-bottom", type=float, default=24, help="pretend gesture-bar height (CSS px)")
    asyncio.run(main(parser.parse_args()))
