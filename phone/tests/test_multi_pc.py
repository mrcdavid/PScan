"""One phone paired with several PCs (e.g. a laptop at home and a desktop at the office)."""

import asyncio
import json

from pscan.discovery import FoundServer
from pscan.state import AppState
from pscan_testing import free_port, make_controller, wait_until


def found(config) -> FoundServer:
    return FoundServer(config.server_id, config.server_name, "127.0.0.1", config.port)


async def pair(c, app, config):
    """Pair the controller with a PC through the manual-address path."""
    await c.dispatch("connect_manual", {"host": f"127.0.0.1:{config.port}"})
    assert c.screen == "pair"
    code, _ = app.state.pairing.current_code()
    await c.dispatch("pair_finish", {"code": code})
    assert c.screen == "scan" and c.connected and c.state.active_id == config.server_id


async def add_ready_page(c):
    await c.dispatch("add_page", {})
    await wait_until(lambda: c.pages and all(p.status == "ready" for p in c.pages))


def test_pair_switch_and_forget(server, second_server, tmp_path):
    (home_app, home), (office_app, office) = server, second_server
    nearby = []  # what the fake network discovery "sees"

    async def scenario():
        c = make_controller(tmp_path, find_pcs=lambda timeout, want_id=None: list(nearby))
        c._spawn(c.upload_worker())

        await pair(c, home_app, home)
        await add_ready_page(c)

        # Add the office PC: home stays paired, scans now go to the office.
        await c.dispatch("add_pc", {})
        assert c.screen == "connect" and c.snapshot()["servers"][0]["active"]
        await c.dispatch("connect_back", {})
        assert c.screen == "scan"
        await c.dispatch("add_pc", {})
        await pair(c, office_app, office)
        assert [s.name for s in c.state.servers] == ["TEST-PC", "OFFICE-PC"]
        assert c.pages == []  # the page already on the home PC can't follow
        await add_ready_page(c)

        # Switch back by hand.
        await c.dispatch("use_pc", {"server_id": home.server_id})
        assert c.state.server.name == "TEST-PC" and c.connected and c.pages == []

        # At the office: home isn't reachable, the office is, nothing would be lost -> auto switch.
        c.state.server.port = free_port()  # home's old address no longer answers
        c.connected = False
        nearby[:] = [found(office)]
        assert await c.try_connect()
        assert c.state.server.name == "OFFICE-PC" and "now go to OFFICE-PC" in c.toast["text"]

        # With pages on the current PC it doesn't switch on its own; it says which PC is here.
        await add_ready_page(c)
        c.state.server.port = free_port()
        c.connected = False
        nearby[:] = [found(home)]
        assert not await c.try_connect()
        assert c.state.server.name == "OFFICE-PC"
        assert "TEST-PC is here" in c.connection[1]
        assert c.state.find(home.server_id).port == home.port  # its latest address is remembered
        snap = c.snapshot()["servers"]
        assert {s["name"]: s["nearby"] for s in snap} == {"TEST-PC": True, "OFFICE-PC": False}

        # Forgetting the active PC moves scans to the other one.
        await c.dispatch("forget_pc", {"server_id": office.server_id})
        assert [s.name for s in c.state.servers] == ["TEST-PC"] and c.state.server.name == "TEST-PC"
        assert c.connected

        # A PC that forgot this phone is removed; with none left the app asks to pair again.
        home_app.state.devices.forget_all()
        c.connected = False
        assert not await c.try_connect()
        assert c.state.servers == [] and c.screen == "connect"

        # Everything above survived in the settings file.
        assert AppState.load(c.state_path).servers == []
        for task in list(c._tasks):
            task.cancel()

    asyncio.run(scenario())


def test_old_single_pc_settings_still_load(tmp_path):
    old = {
        "server": {"server_id": "abc", "name": "LAPTOP", "host": "10.0.0.5", "port": 8765, "token": "t"},
        "session_id": "0123456789abcdef",
        "pending": [],
        "mode": "bw",
        "paper": "A4",
        "ocr": True,
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    state = AppState.load(path)
    assert [s.name for s in state.servers] == ["LAPTOP"] and state.server.name == "LAPTOP"
    assert state.session_id == "0123456789abcdef" and state.mode == "bw"
    state.save(path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "server" not in saved and saved["active_id"] == "abc"
