from dataclasses import dataclass

PROTOCOLS = ("tcp", "udp")
PORT_MIN, PORT_MAX = 0, 65535
ANY_ADDRESS = "0.0.0.0"  # bound to every network interface at once


@dataclass(frozen=True)
class Listener:
    """A port a process listens on -- like a listening socket: incoming
    connections/datagrams for `protocol`/`port` on `address` reach process
    `pid`. A plain record that only checks itself (protocol, port range);
    whether its process exists and may bind the port is PortTable.add()'s
    job.

    Frozen: a listener is filed under its (protocol, address, port) in the
    PortTable, so it must not change underneath it -- to move it, remove it
    and add a new one."""
    protocol: str                 # "tcp" | "udp"
    port: int                     # PORT_MIN..PORT_MAX
    pid: int                      # process the port belongs to
    service: str                  # e.g. "ssh", "http", "dns"
    address: str = ANY_ADDRESS    # one interface's IP, or ANY_ADDRESS for all of them

    def __post_init__(self) -> None:
        if self.protocol not in PROTOCOLS:
            raise ValueError(f"unknown protocol '{self.protocol}' (expected one of {', '.join(PROTOCOLS)})")
        if not PORT_MIN <= self.port <= PORT_MAX:
            raise ValueError(f"port {self.port} out of range {PORT_MIN}-{PORT_MAX}")
