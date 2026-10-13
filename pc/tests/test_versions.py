"""The PC server and the phone app must share one product version."""

import re
import tomllib
from pathlib import Path

import pscan_server

ROOT = Path(__file__).resolve().parents[2]


def test_pc_and_phone_versions_match():
    pc_version = pscan_server.__version__
    phone_version = tomllib.loads((ROOT / "phone" / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["briefcase"][
        "version"
    ]
    controller = (ROOT / "phone" / "src" / "pscan" / "controller.py").read_text(encoding="utf-8")
    fallback = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', controller).group(1)

    assert pc_version == phone_version == fallback, (pc_version, phone_version, fallback)
