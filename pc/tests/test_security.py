"""Security regression tests: text from the network must not reach PowerShell intact."""

import sys
import types

import pytest

from pscan_server import notify, pdf_builder

# Characters PowerShell expands in a double-quoted here-string, plus a few shell ones.
DANGEROUS = "$`\x00\x07\x1b\x7f"


def test_toast_safe_removes_powershell_metacharacters():
    cleaned = notify._toast_safe("Pixel $(whoami) `n phone")
    assert "$" not in cleaned and "`" not in cleaned
    assert "whoami" in cleaned  # text is kept, only the metacharacters are neutralised


@pytest.mark.parametrize("field", ["title", "msg", "launch"])
def test_notifier_sanitises_before_winotify(monkeypatch, field):
    """The device name / file name reach winotify only after sanitisation."""
    captured = {}

    class FakeNotification:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def set_audio(self, *a, **k):
            pass

        def show(self):
            pass

    fake = types.ModuleType("winotify")
    fake.Notification = FakeNotification
    fake.audio = types.SimpleNamespace(Default="default")
    monkeypatch.setitem(sys.modules, "winotify", fake)

    # A hostile device name in an (unauthenticated) pairing request.
    notify.Notifier().pairing_code("123456", "Phone $(calc) `evil")
    for value in (captured["title"], captured["msg"], captured["launch"]):
        assert not any(c in value for c in DANGEROUS), value


def test_safe_stem_strips_shell_metacharacters():
    stem = pdf_builder.safe_stem("in$(voice)`;&!%^")
    assert not any(c in stem for c in "$`;&!%^")


def test_scan_saved_notification_is_clean(monkeypatch):
    captured = {}

    class FakeNotification:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def set_audio(self, *a, **k):
            pass

        def show(self):
            pass

    fake = types.ModuleType("winotify")
    fake.Notification = FakeNotification
    fake.audio = types.SimpleNamespace(Default="default")
    monkeypatch.setitem(sys.modules, "winotify", fake)

    from pathlib import Path

    notify.Notifier().scan_saved(Path(r"C:\Scans\report $(x).pdf"), 2, True, None)
    for value in (captured["title"], captured["msg"], captured["launch"]):
        assert "$" not in value and "`" not in value
