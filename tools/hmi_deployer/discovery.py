"""
tools/hmi_deployer/discovery.py
Layer: 3 (Host Deployer)
Purpose: Find panels on the local network without a fixed address, so the
"Find panels" button in the device popover can fill the target from what the
boards answer for themselves. (CONTRACT section 14, discovery.)

The C daemon listens on UDP 47800 (``daemon.discovery``) and answers a
``{"cmd":"discover"}`` datagram with a unicast ``{"t":"hello",...}``
(CONTRACT 14.1). This module is the Studio's half: broadcast the query from one
SO_BROADCAST socket and collect the hellos before the operator's timeout runs
out, tagging each reply with the address it came from so the list can name the
panel the operator selects.
"""
import json
import socket

DISCOVERY_PORT = 47800

# The discovery datagram the daemon answers with a hello.
DISCOVERY_QUERY = {"cmd": "discover"}


def broadcast_targets():
    """Every address a discovery broadcast should be sent to.

    Returns:
        A list of IPv4 strings: the limited broadcast (255.255.255.255) plus
        each IPv4 interface's directed broadcast. On any failure collecting
        the interfaces, the limited broadcast alone is returned -- a single
        target beats none, and the test asserts only on that one.
    """
    import ipaddress

    targets = ["255.255.255.255"]
    try:
        hostname = socket.gethostname().split(".")[0] or socket.gethostname()
        for host in {hostname, socket.getfqdn()}:
            try:
                info = socket.getaddrinfo(host, None, socket.AF_INET)
            except socket.gaierror:
                continue
            for family, _stype, _proto, _canon, sockaddr in info:
                if family != socket.AF_INET:
                    continue
                interface_ip = sockaddr[0]
                try:
                    network = ipaddress.ip_network(
                        f"{interface_ip}/32", strict=False)
                except ValueError:
                    continue
                directed = str(network.broadcast_address)
                if directed not in targets:
                    targets.append(directed)
    except Exception:
        pass
    return targets


def discover(timeout=1.5, port=DISCOVERY_PORT, targets=None):
    """Send a discovery query and collect the hellos it draws.

    Args:
        timeout: seconds to keep listening for replies.
        port: the daemon's discovery port to send to and listen on.
        targets: the addresses to broadcast to, or None for
            :func:`broadcast_targets`.

    Returns:
        A list of the hello payloads the daemon answered with, each tagged
        with the ``"ip"`` it came from (sender) and de-duplicated by that ip.
        Empty when nothing answers within the timeout.
    """
    if targets is None:
        targets = broadcast_targets()
    query = json.dumps(DISCOVERY_QUERY).encode()

    received = {}

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", port))
        sock.settimeout(timeout)
        for target in targets:
            try:
                sock.sendto(query, (target, port))
            except OSError:
                # A target on a link this host is not on (an "unable to reach"
                # error) is not worth failing the whole scan over.
                continue
        while True:
            try:
                data, addr = sock.recvfrom(4096)
            except OSError:
                # A closed socket raises rather than blocking forever.
                break
            try:
                reply = json.loads(data)
            except (ValueError, TypeError):
                continue
            if reply.get("t") != "hello":
                continue
            sender_ip = addr[0]
            received.setdefault(sender_ip, reply)

    return list(received.values())