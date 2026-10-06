import ipaddress
import json
import socket

from pscan_server.discovery import HERE, QUERY, DiscoveryService, broadcast_addresses


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_replies_to_discovery_query():
    port = _free_udp_port()
    service = DiscoveryService(
        {"id": "abc", "name": "TEST-PC", "port": 8765}, port=port, host="127.0.0.1", beacon_interval=0
    )
    service.start()
    assert service.ready.wait(5)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(3)
            client.sendto(b"garbage", ("127.0.0.1", port))  # ignored, must not crash the service
            client.sendto(json.dumps({"t": QUERY, "v": 1}).encode(), ("127.0.0.1", port))
            data, _ = client.recvfrom(2048)
        reply = json.loads(data)
        assert reply == {"t": HERE, "v": 1, "id": "abc", "name": "TEST-PC", "port": 8765}
    finally:
        service.stop()
        service.join(5)
    assert not service.is_alive()


def test_broadcast_addresses_are_ipv4():
    addresses = broadcast_addresses()
    assert addresses
    for address in addresses:
        ipaddress.IPv4Address(address)
