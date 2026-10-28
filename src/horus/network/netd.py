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


def is_valid_ip(ip):
    octets = ip.split('.')
    return len(octets) == 4 and all(o.isdigit() and 0 <= int(o) <= 255 for o in octets)


class NetDaemon:
    """A daemon that manages network interfaces and ports. Reading the
    interfaces always works; changing them needs the netd process running."""

    PROCESS_NAME = "netd"

    def __init__(self, hardware, process_table, port_table=None, hosts=None):
        self._hardware = hardware
        self._processes = process_table
        self._ports = port_table
        self._hosts = dict(hosts or {}) # server.local -> 10.0.0.5

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

    def resolve(self, host):
        """Resolve a hostname to an IP address, or None if it is unknown. Raises
        NetdNotRunningError for a hostname (not an IP) while netd is not running."""
        if is_valid_ip(host):
            return host
        self._require()
        return self._hosts.get(host)
