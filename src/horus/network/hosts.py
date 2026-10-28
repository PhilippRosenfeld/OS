from dataclasses import dataclass

from horus.network.address import is_valid_ip


class HostError(Exception):
    """Base class for host-related errors."""
    pass

class HostNotFoundError(HostError):
    """Raised when a specified host is not found."""
    def __init__(self, hostname):
        super().__init__(f"Host '{hostname}' not found.")
        
        
@dataclass
class HostEntry:
    """Represents a single host entry with a hostname and its corresponding IP address."""
    name: str
    ip: str
    latency_ms: float = 0.0  # latency in milliseconds, default is 0.0
    online: bool = True  # online status, default is True
    
    
STANDARD_HOSTS = {
    "gateway": HostEntry(name="gateway", ip="192.168.1.1", latency_ms=10.0, online=True),
    "server.local": HostEntry(name="server.local", ip="192.168.1.100", latency_ms=50.0, online=True),
    "mainframe.corp": HostEntry(name="mainframe.corp", ip="192.168.1.200", latency_ms=150.0, online=True)
}
        
class HostTable:
    """A simple mapping of hostnames to IP addresses."""
    
    def __init__(self, hosts: dict[str, HostEntry] | None = None):
        self._hosts = dict(hosts or {})  # e.g., {"server.local": HostEntry(name="server.local", ip="192.168.1.1")}
        
        if STANDARD_HOSTS:
            for hostname, entry in STANDARD_HOSTS.items():
                self._hosts[hostname] = entry
        
        
    def add_host(self, hostname: str, ip: str, latency_ms: float = 0.0, online: bool = True) -> None:
        """Adds a new host entry to the table."""
        
        if hostname in self._hosts:
            raise HostError(f"Host '{hostname}' already exists.")
            
        if not is_valid_ip(ip):
            raise HostError(f"Invalid IP address '{ip}'.")
        
        if not (0 <= latency_ms <= 10000):  # Arbitrary upper limit for latency
            raise HostError(f"Latency {latency_ms} ms is out of valid range (0-10000 ms).")
        
        self._hosts[hostname] = HostEntry(name=hostname, ip=ip, latency_ms=latency_ms, online=online)
        
    def remove_host(self, hostname: str) -> None:
        """Removes a host entry from the table."""
        if hostname not in self._hosts:
            raise HostNotFoundError(hostname)
        del self._hosts[hostname]
        
    def get_host(self, hostname: str) -> HostEntry:
        """Retrieves a host entry by its hostname."""
        if hostname not in self._hosts:
            raise HostNotFoundError(hostname)
        return self._hosts[hostname]
    
    def get_host_by_ip(self, ip: str) -> HostEntry | None:
        """Retrieves a host entry by its IP address."""
        for entry in self._hosts.values():
            if entry.ip == ip:
                return entry
        return None
    
    