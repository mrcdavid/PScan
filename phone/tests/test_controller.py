"""The app's Controller and Bridge against a real PScan server running on this PC."""

import asyncio
import http.client
import json
import urllib.request

from pypdf import PdfReader

from pscan.bridge import Bridge
from pscan_testing import make_controller, wait_until


def test_full_scan_flow(server, tmp_path):
    app, config = server

    async def scenario():
        c = make_controller(tmp_path)
        assert c.screen == "connect"
        # Start the background loops without the network-wide discovery search.
        c._spawn(c.connection_loop())
        c._spawn(c.upload_worker())

        await c.dispatch("connect_manual", {"host": f"127.0.0.1:{config.port}"})
        assert c.screen == "pair" and c.snapshot()["pair"]["server"] == "TEST-PC"
        await c.dispatch("pair_finish", {"code": "000000"})
        assert "Wrong code" in c.pair_error
        code, _ = app.state.pairing.current_code()
        await c.dispatch("pair_finish", {"code": code})
        assert c.screen == "scan" and c.connected

        for _ in range(3):
            await c.dispatch("add_page", {})
        await wait_until(lambda: len(c.pages) == 3 and all(p.status == "ready" and p.thumb for p in c.pages))
        keys = [p.key for p in c.pages]
        assert all(p.cropped for p in c.pages)

        await c.dispatch("rotate", {"key": keys[0]})
        await c.dispatch("move", {"key": keys[0], "delta": 1})
        assert [p.key for p in c.pages] == [keys[1], keys[0], keys[2]]
        await c.dispatch("toggle_crop", {"key": keys[2]})
        assert c.page(keys[2]).crop is False
        await c.dispatch("delete", {"key": keys[2]})
        await c.dispatch("retake", {"key": keys[1]})
        await wait_until(lambda: all(p.status == "ready" and p.thumb for p in c.pages))
        assert len(c.pages) == 2

        await c.dispatch("set_option", {"paper": "Letter", "mode": "bw", "ocr": False})
        assert (c.state.paper, c.state.mode, c.state.ocr) == ("Letter", "bw", False)
        json.dumps(c.snapshot())  # the screen must be able to read it

        await c.dispatch("save", {"name": "Controller test"})
        assert c.saving["state"] == "done", c.saving
        assert c.saving["paper"] == "Letter" and c.pages == []
        reader = PdfReader(config.output_dir / "Controller test.pdf")
        assert len(reader.pages) == 2
        sizes = {tuple(sorted((round(float(p.mediabox.width)), round(float(p.mediabox.height))))) for p in reader.pages}
        assert sizes == {(612, 792)}  # Letter, portrait or landscape

        # Settings survive a restart; leftover photos are cleaned up.
        assert make_controller(tmp_path).state.server.name == "TEST-PC"
        assert not list((tmp_path).glob("*.jpg"))
        for task in list(c._tasks):
            task.cancel()

    asyncio.run(scenario())


def test_bridge_serves_ui_and_state(tmp_path):
    async def scenario():
        loop = asyncio.get_running_loop()
        c = make_controller(tmp_path)
        bridge = Bridge(c, loop)
        bridge.start()
        port = bridge.server.server_address[1]

        def get(path, key=True):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
            if key:
                req.add_header("X-PScan-Key", bridge.key)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()

        def post(name, args, key=True):
            body = json.dumps({"name": name, "args": args}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/action", data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            if key:
                req.add_header("X-PScan-Key", bridge.key)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code

        def raw_get(path):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", path)
            return conn.getresponse().status

        run = lambda fn, *a: loop.run_in_executor(None, fn, *a)  # noqa: E731

        assert (await run(get, "/", False))[0] == 403
        status, html = await run(get, f"/?k={bridge.key}", False)
        assert status == 200 and b"PScan" in html and b"Marc" in html and b"CEAT" not in html
        assert (await run(get, "/ui/app.css", False))[0] == 200
        assert (await run(get, "/ui/app.js", False))[0] == 200
        assert await run(raw_get, "/ui/../bridge.py") == 404
        assert (await run(get, "/api/state", False))[0] == 403

        status, body = await run(get, "/api/state?since=0")
        state = json.loads(body)
        assert status == 200 and state["screen"] == "connect" and state["options"]["paper"] == "A4"
        assert state["app"]["year"] == 2026

        # A long poll returns as soon as something changes.
        waiter = run(get, f"/api/state?since={state['v']}")
        await asyncio.sleep(0.3)
        assert await run(post, "set_option", {"ocr": False}) == 202
        status, body = await asyncio.wait_for(waiter, 5)
        assert json.loads(body)["options"]["ocr"] is False
        assert await run(post, "set_option", {"ocr": True}, False) == 403

        bridge.stop()

    asyncio.run(scenario())
