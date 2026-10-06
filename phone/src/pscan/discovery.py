"""Find PCs running PScan on the local network (UDP broadcast, stdlib only)."""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from dataclasses import dataclass

DISCOVERY_PORT = 8766
QUERY = {"t": "pscan-discover", "v": 1}


@dataclass(frozen=True)
class FoundServer:
    server_id: str
    name: str
    host: str
    port: int


def local_ip() -> str | None:
    """This device's IP on the network it would use to reach the LAN."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # nothing is sent
            return s.getsockname()[0]
        except OSError:
            return None


def _targets(extra: tuple[str, ...]) -> list[str]:
    targets = ["255.255.255.255", *extra]
    ip = local_ip()
    if ip and not ip.startswith("127."):
        # Most home/hotspot networks are /24; a directed broadcast is more reliable on Android.
        targets.append(str(ipaddress.IPv4Network(f"{ip}/24", strict=False).broadcast_address))
    return list(dict.fromkeys(targets))


def _parse(data: bytes, address: str) -> FoundServer | None:
    try:
        message = json.loads(data.decode())
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(message, dict) or message.get("t") != "pscan-here":
        return None
    try:
        return FoundServer(str(message["id"]), str(message["name"]), address, int(message["port"]))
    except (KeyError, TypeError, ValueError):
        return None


def discover(
    timeout: float = 3.0,
    want_id: str | None = None,
    port: int = DISCOVERY_PORT,
    extra_targets: tuple[str, ...] = (),
    listen: bool = True,
) -> list[FoundServer]:
    """Ask the network for PScan PCs and listen for their beacons for ``timeout`` seconds.

    Returns as soon as ``want_id`` is found, if given. ``listen=False`` skips binding the
    discovery port (only replies to our own queries are received).
    """
    found: dict[str, FoundServer] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            if not listen:
                raise OSError
            sock.bind(("", port))  # lets us also hear the PCs' periodic beacons
        except OSError:
            sock.bind(("", 0))  # e.g. the PScan server itself runs on this machine
        sock.settimeout(0.25)
        query = json.dumps(QUERY).encode()
        targets = _targets(extra_targets)
        deadline = time.monotonic() + timeout
        next_query = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_query:
                for target in targets:
                    try:
                        sock.sendto(query, (target, port))
                    except OSError:
                        pass
                next_query = time.monotonic() + 1.0
            try:
                data, (address, _) = sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                time.sleep(0.05)
                continue
            server = _parse(data, address)
            if server:
                found[server.server_id] = server
                if want_id and server.server_id == want_id:
                    break
    finally:
        sock.close()
    return sorted(found.values(), key=lambda s: s.name.lower())
