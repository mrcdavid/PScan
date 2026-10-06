"""The phone app's network code against a real PScan server running on this PC.

Run from the project root with the PC venv (it has the server's packages):
    pc\\.venv\\Scripts\\python -m pytest phone\\tests
"""

import pytest
from pypdf import PdfReader

from pscan.client import ConnectionFailed, NotFound, PScanClient, Unauthorized
from pscan.discovery import discover
from pscan_testing import free_port, photo_bytes


def test_discover_finds_server(server):
    app, config = server
    found = discover(timeout=2, port=config.discovery_port, extra_targets=("127.0.0.1",), listen=False)
    match = [f for f in found if f.server_id == config.server_id]
    assert match and match[0].name == "TEST-PC" and match[0].port == config.port


def test_pair_and_scan(server):
    app, config = server
    client = PScanClient("127.0.0.1", config.port)
    assert client.health()["name"] == "TEST-PC"

    with pytest.raises(Unauthorized):
        client.create_session()

    pair_id = client.pair_start("Test phone")
    code, _ = app.state.pairing.current_code()
    result = client.pair_finish(pair_id, code)
    client.token = result["token"]
    assert result["server_id"] == config.server_id
    assert client.me()["device"] == "Test phone"

    sid = client.create_session()["id"]
    first = client.upload_page(sid, photo_bytes())
    second = client.upload_page(sid, photo_bytes())
    assert first["cropped"] is True
    assert client.preview(sid, first["id"], "bw")[:2] == b"\xff\xd8"
    assert client.update_page(sid, first["id"], rotate=90)["rotation"] == 90
    assert client.update_page(sid, first["id"], crop=False)["crop"] is False
    order = [second["id"], first["id"]]
    assert [p["id"] for p in client.reorder(sid, order)["pages"]] == order
    retaken = client.upload_page(sid, photo_bytes(), replace=second["id"])
    assert retaken["id"] == second["id"]

    saved = client.finish(sid, "Phone test", "gray", ocr=False)
    assert saved["filename"] == "Phone test.pdf" and saved["pages"] == 2
    assert len(PdfReader(config.output_dir / "Phone test.pdf").pages) == 2

    with pytest.raises(NotFound):
        client.get_session(sid)


def test_wrong_code_message(server):
    app, config = server
    client = PScanClient("127.0.0.1", config.port)
    pair_id = client.pair_start("Test phone")
    with pytest.raises(Exception) as info:
        client.pair_finish(pair_id, "not the code")
    assert "Wrong code" in str(info.value)


def test_unreachable_pc():
    client = PScanClient("127.0.0.1", free_port(), timeout=2)
    with pytest.raises(ConnectionFailed):
        client.health()
