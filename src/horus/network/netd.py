import ipaddress
from dataclasses import dataclass

from horus.hardware.network_interface import NetworkInterface
from horus.network.address import is_valid_ip
from horus.network.hosts import HostNotFoundError, HostTable


@dataclass  
class Route:
    iface: NetworkInterface
    via: str | None  # the next hop's IP address, or None for a directly connected host

class NetdError(Exception):
    """Base class for netd-related errors."""

class NetdNotRunningError(NetdError):
    """Raised when the netd service is not running."""
    def __init__(self):
        super().__init__("netd is not running")

class NetdInterfaceNotFoundError(NetdError):
    """Raised when a specified network interface is not found."""
    def __init__(self, iface_name):
        super().__init__(f"Interface '{iface_name}' not found.")

class NetdInvalidConfigError(NetdError):
    """Raised when a configuration value (IP address, link speed) is rejected."""
    def __init__(self, message):
        super().__init__(f"Invalid configuration: {message}")
    
class NetdNoRouteError(NetdError):
    """Raised when a route to a host cannot be found."""
    def __init__(self, host):
        super().__init__(f"Network unreachable: No route to {host}")


class NetDaemon:
    """A daemon that manages network interfaces and ports. Reading the
    interfaces always works; changing them needs the netd process running."""

    PROCESS_NAME = "netd"

    def __init__(self, hardware, process_table, hosts: HostTable | None = None, port_table=None, gateway: str | None = None):
        self._hardware = hardware
        self._processes = process_table
        self._ports = port_table
        self._dns = hosts if hosts is not None else HostTable()  # hostname -> IP address
        self._gateway = gateway if gateway is not None else self._default_gateway()

    def _default_gateway(self):
        """The IP of the host called 'gateway' in the host table, if there is one."""
        try:
            return self._dns.get_host("gateway").ip
        except HostNotFoundError:
            return None

    def is_running(self):
        """Returns True if the netd process is running, False otherwise."""
        return any(p.name == self.PROCESS_NAME for p in self._processes.list_processes())

    def _require(self):
        if not self.is_running():
            raise NetdNotRunningError()

    def interface(self, name):
        return next((i for i in self._hardware.motherboard.network_interfaces if i.name == name), None)

    def _configurable(self, name):
        """The interface to change -- only while netd runs and the interface exists."""
        self._require()
        iface = self.interface(name)
        if iface is None:
            raise NetdInterfaceNotFoundError(name)
        return iface

    def set_enabled(self, name, enabled):
        iface = self._configurable(name)
        iface.enabled = enabled
        return iface

    def set_ip(self, name, ip):
        iface = self._configurable(name)
        if not is_valid_ip(ip):
            raise NetdInvalidConfigError(f"Invalid IP address: {ip}")
        iface.ip_address = ip
        return iface

    def set_speed(self, name, down_mbps, up_mbps):
        iface = self._configurable(name)
        if down_mbps < 0 or up_mbps < 0:
            raise NetdInvalidConfigError("Speeds must not be negative.")
        iface.link_speed_down_mbps = down_mbps
        iface.link_speed_up_mbps = up_mbps
        return iface
    
    def set_gateway(self, ip):
        """Set the default gateway for outgoing connections. Raises
        NetdInvalidConfigError if `ip` is not a valid IP address."""
        self._require()
        if not is_valid_ip(ip):
            raise NetdInvalidConfigError(f"Invalid IP address: {ip}")
        self._gateway = ip

    def resolve(self, name_or_ip):
        """Resolve a hostname to an IP address, or None if it is unknown. Raises
        NetdNotRunningError for a hostname (not an IP) while netd is not running."""
        if is_valid_ip(name_or_ip):
            return name_or_ip
        self._require()
        try:
            return self._dns.get_host(name_or_ip).ip
        except HostNotFoundError:
            return None
        
    @property
    def gateway(self) -> str | None:
        return self._gateway

    def route(self, ip) -> Route:
        """How `ip` is reached: directly, if it lies in the network of an
        interface that is UP, otherwise via the gateway -- if that lies in
        one. Only reads the configuration, so it works without netd running.
        Raises NetdNoRouteError if neither applies."""
        target = ipaddress.ip_address(ip)
        up = [i for i in self._hardware.motherboard.network_interfaces if i.enabled]
        for iface in up:                                    # 1. directly connected?
            if target in iface.network:
                return Route(iface, via=None)
        if self._gateway is not None:                       # 2. via the gateway
            gateway = ipaddress.ip_address(self._gateway)
            for iface in up:
                if gateway in iface.network:
                    return Route(iface, via=self._gateway)
        raise NetdNoRouteError(ip)
