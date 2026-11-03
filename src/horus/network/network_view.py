"""Text tables of the network state, shared by netman's commands and the
'sys' Network screen so the two can never show it differently."""

from horus.network.netd import NetdNoRouteError


def route_table_lines(hardware, netd) -> list[str]:
    """One direct route per interface (its network), plus the default
    route via the gateway -- 'unreachable' if no UP interface reaches it.
    Without a netd there is no gateway known, so no default route."""
    lines = [f"{'Destination':<18} {'Gateway':<15} {'Iface':<6} Status", "-" * 48]
    for iface in hardware.motherboard.network_interfaces:
        status = "UP" if iface.enabled else "DOWN"
        lines.append(f"{str(iface.network):<18} {'-':<15} {iface.name:<6} {status}")
    gateway = netd.gateway if netd is not None else None
    if gateway is None:
        return lines
    try:
        iface_name, status = netd.route(gateway).iface.name, "UP"
    except NetdNoRouteError:
        iface_name, status = "-", "unreachable"
    lines.append(f"{'default':<18} {gateway:<15} {iface_name:<6} {status}")
    return lines


def port_lines(port_table) -> list[str]:
    """Every open port with the process listening on it."""
    listeners = port_table.list() if port_table is not None else []
    if not listeners:
        return ["No open ports."]
    lines = [f"{'Protocol':<10} {'Port':<6} {'Address':<15} {'PID':<6} {'Service':<20}", "-" * 60]
    for listener in listeners:
        lines.append(f"{listener.protocol:<10} {listener.port:<6} {listener.address:<15} {listener.pid:<6} {listener.service:<20}")
    return lines


def host_lines(host_table) -> list[str]:
    """The known hosts with their address, latency and whether they answer."""
    hosts = host_table.list_hosts() if host_table is not None else []
    if not hosts:
        return ["No known hosts."]
    lines = [f"{'Host':<18} {'Address':<15} {'Latency':<9} Status", "-" * 50]
    for host in hosts:
        lines.append(f"{host.name:<18} {host.ip:<15} {f'{host.latency_ms:.0f} ms':<9} "
                     f"{'online' if host.online else 'offline'}")
    return lines
