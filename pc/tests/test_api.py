import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from pscan_samples import make_photo, to_jpeg
from pscan_server.notify import NullNotifier
from pscan_server.server import create_app


@pytest.fixture
def app(config):
    return create_app(config, notifier=NullNotifier())


@pytest.fixture
def client(app):
    return TestClient(app)


def pair(client, app) -> dict:
    pair_id = client.post("/api/pair/start", json={"device_name": "Reno 13F"}).json()["pair_id"]
    code, name = app.state.pairing.current_code()
    assert name == "Reno 13F"
    resp = client.post("/api/pair/finish", json={"pair_id": pair_id, "code": code})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture
def auth(client, app):
    return pair(client, app)


def test_health(client):
    body = client.get("/api/health").json()
    assert body["app"] == "pscan" and body["name"] == "TEST-PC" and len(body["server_id"]) == 32


def test_requires_pairing(client):
    assert client.post("/api/sessions").status_code == 401
    assert client.post("/api/sessions", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_pairing_shows_code_and_issues_token(client, app):
    headers = pair(client, app)
    assert client.get("/api/me", headers=headers).json()["device"] == "Reno 13F"
    title, _ = app.state.notifier.shown[-1]
    assert "pairing code" in title.lower()


def test_wrong_codes_lock_the_request(client, app):
    pair_id = client.post("/api/pair/start", json={"device_name": "X"}).json()["pair_id"]
    code, _ = app.state.pairing.current_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert client.post("/api/pair/finish", json={"pair_id": pair_id, "code": wrong}).status_code == 400
    # Even the right code is refused now.
    resp = client.post("/api/pair/finish", json={"pair_id": pair_id, "code": code})
    assert resp.status_code == 400 and "new code" in resp.json()["detail"]


def test_pairing_rate_limit(client):
    statuses = [client.post("/api/pair/start", json={"device_name": "X"}).status_code for _ in range(8)]
    assert statuses[:6] == [200] * 6 and 429 in statuses


def test_forget_devices_revokes_token(client, app, auth):
    assert client.get("/api/me", headers=auth).status_code == 200
    app.state.devices.forget_all()
    assert client.get("/api/me", headers=auth).status_code == 401


def test_full_scan_flow(client, app, auth, config):
    sid = client.post("/api/sessions", headers=auth).json()["id"]
    upload = lambda data, **params: client.post(  # noqa: E731
        f"/api/sessions/{sid}/pages", content=data, headers={**auth, "Content-Type": "image/jpeg"}, params=params
    )

    ids = []
    for seed in range(3):
        photo, _ = make_photo(seed=seed)
        resp = upload(to_jpeg(photo))
        assert resp.status_code == 200, resp.text
        assert resp.json()["cropped"] is True
        ids.append(resp.json()["id"])

    # Retake page 2 (same id, new photo).
    photo, _ = make_photo(seed=9)
    assert upload(to_jpeg(photo), replace=ids[1]).json()["id"] == ids[1]

    # Preview in each mode.
    for mode in ("color", "gray", "bw"):
        resp = client.get(f"/api/sessions/{sid}/pages/{ids[0]}/preview.jpg", params={"mode": mode}, headers=auth)
        assert resp.status_code == 200 and resp.headers["content-type"] == "image/jpeg"
        assert resp.content[:2] == b"\xff\xd8"

    # Rotate, crop off, reorder, delete.
    assert (
        client.patch(f"/api/sessions/{sid}/pages/{ids[0]}", json={"rotate": 90}, headers=auth).json()["rotation"] == 90
    )
    assert (
        client.patch(f"/api/sessions/{sid}/pages/{ids[2]}", json={"crop": False}, headers=auth).json()["crop"] is False
    )
    assert client.patch(f"/api/sessions/{sid}/pages/{ids[0]}", json={"rotate": 45}, headers=auth).status_code == 400
    order = [ids[2], ids[0], ids[1]]
    assert [
        p["id"]
        for p in client.put(f"/api/sessions/{sid}/order", json={"page_ids": order}, headers=auth).json()["pages"]
    ] == order
    assert client.put(f"/api/sessions/{sid}/order", json={"page_ids": ids[:2]}, headers=auth).status_code == 400
    remaining = client.delete(f"/api/sessions/{sid}/pages/{ids[1]}", headers=auth).json()["pages"]
    assert [p["id"] for p in remaining] == [ids[2], ids[0]]

    # Session survives a "phone restart".
    assert len(client.get(f"/api/sessions/{sid}", headers=auth).json()["pages"]) == 2

    resp = client.post(f"/api/sessions/{sid}/finish", json={"name": "Bill", "mode": "bw", "ocr": False}, headers=auth)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "Bill.pdf" and body["pages"] == 2
    assert body["paper"] == "A4"  # the default
    pdf = config.output_dir / "Bill.pdf"
    reader = PdfReader(pdf)
    assert len(reader.pages) == 2
    # Every page is exactly A4 (595 x 842 pt). Both are landscape: page 1 is the uncropped
    # (landscape) photo, page 2 the portrait page rotated by 90 degrees.
    for page in reader.pages:
        assert (float(page.mediabox.width), float(page.mediabox.height)) == pytest.approx((841.9, 595.3), abs=0.4)

    # Session is gone after saving; a toast was shown.
    assert client.get(f"/api/sessions/{sid}", headers=auth).status_code == 404
    assert app.state.notifier.shown[-1][0] == "Scan saved: Bill.pdf"


def test_finish_empty_session(client, auth):
    sid = client.post("/api/sessions", headers=auth).json()["id"]
    resp = client.post(f"/api/sessions/{sid}/finish", json={}, headers=auth)
    assert resp.status_code == 400


def test_bad_uploads(client, auth):
    sid = client.post("/api/sessions", headers=auth).json()["id"]
    url = f"/api/sessions/{sid}/pages"
    assert client.post(url, content=b"", headers=auth).status_code == 400
    assert client.post(url, content=b"definitely not a jpeg", headers=auth).status_code == 400
    photo, _ = make_photo()
    assert (
        client.post(url, content=to_jpeg(photo), headers=auth, params={"replace": "0123456789abcdef"}).status_code
        == 404
    )


def test_unknown_or_malicious_ids(client, auth):
    assert client.get("/api/sessions/0123456789abcdef", headers=auth).status_code == 404
    assert client.get("/api/sessions/..%2F..%2Fdevices", headers=auth).status_code == 404
    assert client.delete("/api/sessions/not-an-id", headers=auth).status_code == 404


def test_session_cleanup(app, auth, client):
    sid = client.post("/api/sessions", headers=auth).json()["id"]
    assert app.state.store.cleanup(max_age=3600) == 0
    assert app.state.store.cleanup(max_age=-1) == 1
    assert client.get(f"/api/sessions/{sid}", headers=auth).status_code == 404


def test_paper_sizes(client, auth, config):
    assert client.get("/api/health").json()["default_paper"] == "A4"
    sid = client.post("/api/sessions", headers=auth).json()["id"]
    photo, _ = make_photo()
    pid = client.post(f"/api/sessions/{sid}/pages", content=to_jpeg(photo), headers=auth).json()["id"]
    url = f"/api/sessions/{sid}/pages/{pid}/preview.jpg"
    assert client.get(url, params={"paper": "Letter"}, headers=auth).status_code == 200
    assert client.get(url, params={"paper": "B5"}, headers=auth).status_code == 400
    resp = client.post(f"/api/sessions/{sid}/finish", json={"paper": "Letter", "ocr": False}, headers=auth)
    assert resp.status_code == 200 and resp.json()["paper"] == "Letter"
    box = PdfReader(config.output_dir / resp.json()["filename"]).pages[0].mediabox
    assert (float(box.width), float(box.height)) == pytest.approx((612, 792), abs=0.4)
