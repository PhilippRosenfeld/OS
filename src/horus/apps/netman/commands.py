import random

from horus.kernel.registry import Registry, command
from horus.network.address import is_valid_ip
from horus.network.hosts import HostEntry
from horus.network.listener import ANY_ADDRESS
from horus.network.netd import NetdError, NetdNotRunningError

netman_commands = Registry()

PING_DEFAULT_COUNT = 4
PING_MAX_COUNT = 20

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
    count = max(1, min(int(argv[1]), PING_MAX_COUNT)) if len(argv) == 2 else PING_DEFAULT_COUNT

    ip_address = _resolve_target(ctx, target)
    if ip_address is None:
        return

    iface = next((i for i in ctx.hardware.motherboard.network_interfaces if i.enabled), None)
    if iface is None:
        ctx.write_line("ping: Network is unreachable (no interface is UP)")
        return

    host = _ping_target_host(ctx, iface, ip_address)
    ctx.write_line(f"Pinging {target} [{ip_address}] via {iface.name} with 32 bytes of data:")
    times = []
    for _ in range(count):
        if host is None or random.random() * 100 < iface.packet_loss_percentage:
            ctx.write_line("Request timed out.")
            continue
        rtt = max(0.0, (iface.latency_ms + host.latency_ms) * random.uniform(0.8, 1.2))
        times.append(rtt)
        ctx.write_line(f"Reply from {ip_address}: bytes=32 time={rtt:.0f}ms TTL=64")

    lost = count - len(times)
    ctx.write_line(f"Ping statistics for {ip_address}:")
    ctx.write_line(f"    Packets: Sent = {count}, Received = {len(times)}, Lost = {lost} ({lost * 100 // count}% loss)")
    if times:
        ctx.write_line(f"    Round trip: min = {min(times):.0f}ms, max = {max(times):.0f}ms, "
                       f"avg = {sum(times) / len(times):.0f}ms")


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


def _ping_target_host(ctx, iface, ip_address):
    """The HostEntry answering at ip_address, or None if nothing does (unknown
    or offline) -- the pings then just time out. Pinging the interface's own
    address always answers, instantly."""
    if ip_address == iface.ip_address or ip_address.startswith("127."):
        return HostEntry(name="localhost", ip=ip_address, latency_ms=0.0)
    host = ctx.host_table.get_host_by_ip(ip_address) if ctx.host_table is not None else None
    return host if host is not None and host.online else None


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
