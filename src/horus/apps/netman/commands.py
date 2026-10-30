import random
from dataclasses import dataclass

from horus.kernel.registry import Registry, command
from horus.network.address import is_valid_ip
from horus.network.listener import ANY_ADDRESS
from horus.network.netd import NetdError, NetdNoRouteError, NetdNotRunningError
from horus.shell.jobs import run_timed

netman_commands = Registry()

PING_DEFAULT_COUNT = 4
PING_MAX_COUNT = 20
PING_INTERVAL_S = 0.5   # pause between two packets
PING_TIMEOUT_S = 1.0    # how long a lost packet is waited for

@command("status", help_text="Show the network interfaces", target=netman_commands)
def status(ctx, argv):
    for iface in ctx.hardware.motherboard.network_interfaces:
        ctx.write_line(f"{iface.name}  {iface.ip_address}  {'UP' if iface.enabled else 'DOWN'}")

@command("iface", help_text="Show the network interface details", target=netman_commands)
def iface(ctx, argv):
    if len(argv) < 1:
        ctx.write_line("Usage: iface <interface_name>")
        return

    iface_name = argv[0]
    iface = next((i for i in ctx.hardware.motherboard.network_interfaces if i.name == iface_name), None)

    if iface is None:
        ctx.write_line(f"Interface '{iface_name}' not found.")
        return
        
    ctx.write_line(f"Interface   | {iface.name}")
    ctx.write_line(f"IP Address  | {iface.ip_address}")
    ctx.write_line(f"MAC Address | {iface.mac_address}")
    ctx.write_line(f"Link Speed  | {iface.link_speed_down_mbps}/{iface.link_speed_up_mbps} Mbps (down/up)")
    ctx.write_line(f"Latency     | {iface.latency_ms} ms")
    ctx.write_line(f"Packet Loss | {iface.packet_loss_percentage} %")
    ctx.write_line(f"Status      | {'UP' if iface.enabled else 'DOWN'}")
    
    if ctx.port_table is None:
        return
    bound = [listener for listener in ctx.port_table.list()
             if listener.address in (iface.ip_address, ANY_ADDRESS)]
    ctx.write_line("-" * 40)
    ctx.write_line("Ports" if bound else "Ports: none")
    ctx.write_line(f"{'Proto':<6} {'Port':<8} {'State':<8} {'Service'}")
    for listener in bound:
        ctx.write_line(f" {listener.protocol:<6} {listener.port:<7} {_port_state(listener, iface):<9} {listener.service}")

@command("up", help_text="Bring up the specified network interface", target=netman_commands)
def up(ctx, argv):
    if len(argv) < 1:
        ctx.write_line("Usage: up <interface_name>")
        return
    iface = _configure(ctx, lambda netd: netd.set_enabled(argv[0], True))
    if iface is not None:
        ctx.write_line(f"Interface '{iface.name}' is now UP.")

@command("down", help_text="Bring down the specified network interface", target=netman_commands)
def down(ctx, argv):
    if len(argv) < 1:
        ctx.write_line("Usage: down <interface_name>")
        return
    iface = _configure(ctx, lambda netd: netd.set_enabled(argv[0], False))
    if iface is not None:
        ctx.write_line(f"Interface '{iface.name}' is now DOWN.")

@command("set-ip", help_text="Set the IP address of the specified network interface", target=netman_commands)
def set_ip(ctx, argv):
    if len(argv) < 2:
        ctx.write_line("Usage: set-ip <interface_name> <ip_address>")
        return
    iface = _configure(ctx, lambda netd: netd.set_ip(argv[0], argv[1]))
    if iface is not None:
        ctx.write_line(f"Interface '{iface.name}' IP address set to {iface.ip_address}.")

@command("speed", help_text="Set the speed of the specified network interface", target=netman_commands)
def speed(ctx, argv):
    if len(argv) < 3:
        ctx.write_line("Usage: speed <interface_name> <down_mbps> <up_mbps>")
        return
    try:
        down_mbps, up_mbps = int(argv[1]), int(argv[2])
    except ValueError:
        ctx.write_line("Usage: speed <interface_name> <down_mbps> <up_mbps>")
        return
    iface = _configure(ctx, lambda netd: netd.set_speed(argv[0], down_mbps, up_mbps))
    if iface is not None:
        ctx.write_line(f"Interface '{iface.name}' speed set to {down_mbps}/{up_mbps} Mbps (down/up).")

@command("ports", help_text="List the open ports and their associated processes", target=netman_commands)
def ports(ctx, argv):
    port_table = ctx.port_table
    listeners = port_table.list()
    if not listeners:
        ctx.write_line("No open ports.")
        return

    ctx.write_line(f"{'Protocol':<10} {'Port':<6} {'Address':<15} {'PID':<6} {'Service':<20}")
    ctx.write_line("-" * 60)
    for listener in listeners:
        ctx.write_line(f"{listener.protocol:<10} {listener.port:<6} {listener.address:<15} {listener.pid:<6} {listener.service:<20}")
        
@command("ping", help_text="Ping a host to check its reachability", target=netman_commands)
def ping(ctx, argv):
    if len(argv) < 1 or len(argv) > 2 or (len(argv) == 2 and not argv[1].isdigit()):
        ctx.write_line("Usage: ping <hostname_or_ip> [count]")
        return
    target = argv[0]
    count = max(0, min(int(argv[1]), PING_MAX_COUNT)) if len(argv) == 2 else PING_DEFAULT_COUNT
    
    if count == 0:
        ctx.write_line(f"No pakets sent")
        return

    ip_address = _resolve_target(ctx, target)
    if ip_address is None:
        return

    path = _ping_path(ctx, ip_address)
    if path is None:
        return

    via = f"{path.device}, gateway [{path.gateway}]" if path.gateway else path.device
    ctx.write_line(f"Pinging {target} [{ip_address}] via {via} with 32 bytes of data:")
    sent = 0
    times = []

    def packets():
        """One step per packet: it shows up after its round trip (a lost one
        after the timeout), the next one is sent PING_INTERVAL later."""
        nonlocal sent
        for i in range(count):
            gap = PING_INTERVAL_S if i > 0 else 0.0
            if path.latency_ms is None or random.random() * 100 < path.packet_loss_percentage:
                yield gap + PING_TIMEOUT_S, lambda: ctx.write_line("Request timed out.")
            else:
                rtt = max(0.0, path.latency_ms * random.uniform(0.8, 1.2))
                yield gap + rtt / 1000, lambda rtt=rtt: _reply(rtt)
            sent += 1

    def _reply(rtt):
        times.append(rtt)
        ctx.write_line(f"Reply from {ip_address}: bytes=32 time={rtt:.0f}ms TTL=64")

    def statistics():
        if sent == 0:
            return
        lost = sent - len(times)
        ctx.write_line(f"Ping statistics for {ip_address}:")
        ctx.write_line(f"    Packets: Sent = {sent}, Received = {len(times)}, Lost = {lost} ({lost * 100 // sent}% loss)")
        if times:
            ctx.write_line(f"    Round trip: min = {min(times):.0f}ms, max = {max(times):.0f}ms, "
                           f"avg = {sum(times) / len(times):.0f}ms")

    run_timed(ctx, packets(), finish=statistics)


def _resolve_target(ctx, target):
    """The IP to ping, or None after printing why there is none. IPs work
    without netd -- only names need it (and its DNS records)."""
    if is_valid_ip(target):
        return target
    try:
        if ctx.netd is None:
            raise NetdNotRunningError()
        ip_address = ctx.netd.resolve(target)
    except NetdNotRunningError:
        ctx.write_line(f"ping: cannot resolve '{target}': netd is not running")
        return None
    if ip_address is None:
        ctx.write_line(f"ping: unknown host '{target}'")
    return ip_address


@dataclass(frozen=True)
class _PingPath:
    """How the pings travel: out of `device`, via `gateway` (None: the
    target is in the local network), taking latency_ms per round trip --
    None if nothing answers at the other end (unknown or offline host, or
    a gateway that is down), so every packet times out."""
    device: str
    gateway: str | None
    latency_ms: float | None
    packet_loss_percentage: float


def _ping_path(ctx, ip_address):
    """The _PingPath to ip_address, or None after printing why there is no
    route. The own addresses (and 127.x) always answer, instantly."""
    interfaces = ctx.hardware.motherboard.network_interfaces
    own = next((i for i in interfaces if i.enabled and i.ip_address == ip_address), None)
    if own is not None or ip_address.startswith("127."):
        return _PingPath(own.name if own is not None else "lo", None, 0.0, 0.0)

    if ctx.netd is None:
        ctx.write_line(f"ping: Network unreachable: No route to {ip_address}")
        return None
    try:
        route = ctx.netd.route(ip_address)
    except NetdNoRouteError as error:
        ctx.write_line(f"ping: {error}")
        return None

    latency = route.iface.latency_ms
    for hop in ([route.via] if route.via else []) + [ip_address]:   # the gateway, then the target
        host = ctx.host_table.get_host_by_ip(hop) if ctx.host_table is not None else None
        if host is None or not host.online:
            latency = None
            break
        latency += host.latency_ms
    return _PingPath(route.iface.name, route.via, latency, route.iface.packet_loss_percentage)


def _port_state(listener, iface) -> str:
    """Not stored on the Listener -- derived from its protocol and the interface."""
    if not iface.enabled:
        return "DOWN"
    return "LISTEN" if listener.protocol == "tcp" else "  -"


def _configure(ctx, change):
    """Runs a change through netd -- the only way to reconfigure an interface.
    Returns the changed interface, or None after printing why it was refused."""
    try:
        if ctx.netd is None:
            raise NetdNotRunningError()
        return change(ctx.netd)
    except NetdError as error:
        ctx.write_line(str(error))
        return None
