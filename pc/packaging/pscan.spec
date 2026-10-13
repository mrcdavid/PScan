# PyInstaller spec for PScan.exe (one-folder, windowed).
# Built via pc\build_windows.ps1 (sets the working dir to pc\ so relative paths resolve).
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PC_DIR = Path(os.getcwd()).resolve()
REPO = PC_DIR.parent
VERSION = os.environ.get("PSCAN_VERSION", "0.0.0")

hidden = collect_submodules("uvicorn") + ["pystray._win32", "winotify"]

# Ship the config template (seeded into the user's home on first run; no hardcoded
# output_dir, so the installed app defaults to %USERPROFILE%\PScan Scans) and the icon.
datas = [
    (str(PC_DIR / "packaging" / "config.template.toml"), "."),
    (str(REPO / "phone" / "icons" / "pscan.ico"), "."),
]

a = Analysis(
    [str(PC_DIR / "packaging" / "pscan_main.py")],
    pathex=[str(PC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "ruff", "pip", "setuptools"],
    noarchive=False,
)

# Drop OpenCV's unused FFmpeg video codec (~25 MB; PScan only decodes still images).
a.binaries = [b for b in a.binaries if "opencv_videoio_ffmpeg" not in b[0].lower()]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PScan",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # windowed: no console window
    icon=str(REPO / "phone" / "icons" / "pscan.ico"),
    version=str(PC_DIR / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PScan",
)
