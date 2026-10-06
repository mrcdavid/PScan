"""Let the phone find this PC on the local network without typing an IP address.

Two mechanisms, both on UDP ``discovery_port``:
* the phone broadcasts ``{"t": "pscan-discover"}`` and we reply to the sender;
* we broadcast ``{"t": "pscan-here", ...}`` every few seconds (helps when the PC is
  connected to the phone's hotspot, where the phone's own broadcast may go out on
  mobile data instead).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import threading
import time

import psutil

log = logging.getLogger(__name__)

QUERY = "pscan-discover"
HERE = "pscan-here"
PROTOCOL_VERSION = 1


def broadcast_addresses() -> list[str]:
    """Directed broadcast address of every active IPv4 network adapter."""
    result = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        if name in stats and not stats[name].isup:
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET or not addr.netmask:
                continue
            ip = ipaddress.IPv4Address(addr.address)
            if ip.is_loopback or ip.is_link_local:
                continue
            network = ipaddress.IPv4Network(f"{addr.address}/{addr.netmask}", strict=False)
            if network.prefixlen >= 31:
                continue
            result.append(str(network.broadcast_address))
    return sorted(set(result)) or ["255.255.255.255"]


class DiscoveryService(threading.Thread):
    def __init__(self, info: dict, port: int, host: str = "", beacon_interval: float = 3.0):
        super().__init__(name="pscan-discovery", daemon=True)
        self.info = {"t": HERE, "v": PROTOCOL_VERSION, **info}
        self.port = port
        self.host = host
        self.beacon_interval = beacon_interval
        self._stop_event = threading.Event()
        self.ready = threading.Event()
        self.sock: socket.socket | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def _payload(self) -> bytes:
        return json.dumps(self.info).encode()

    def _beacon(self) -> None:
        for address in broadcast_addresses():
            try:
                self.sock.sendto(self._payload(), (address, self.port))
            except OSError:
                pass  # adapter went away, no route, etc.

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: don't let other sockets share the port
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((self.host, self.port))
        except OSError as exc:
            log.error("Discovery disabled: cannot use UDP port %d (%s)", self.port, exc)
            self.ready.set()
            return
        sock.settimeout(0.5)
        self.sock = sock
        self.ready.set()
        log.info("Discovery listening on UDP %d", self.port)

        next_beacon = 0.0
        while not self._stop_event.is_set():
            if self.beacon_interval and time.monotonic() >= next_beacon:
                self._beacon()
                next_beacon = time.monotonic() + self.beacon_interval
            try:
                data, addr = sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                # Windows reports ICMP "port unreachable" from earlier sends as an error here.
                self._stop_event.wait(0.05)
                continue
            try:
                message = json.loads(data.decode())
            except (UnicodeDecodeError, ValueError):
                continue
            if isinstance(message, dict) and message.get("t") == QUERY:
                try:
                    sock.sendto(self._payload(), addr)
                except OSError as exc:
                    log.debug("Discovery reply to %s failed: %s", addr, exc)
        sock.close()
