"""The system's open ports -- the network counterpart to ProcessTable.
Ports belong to processes (a service listens on one), not to network
interfaces: an interface only contributes the IP address a port can be
bound to."""

from typing import TYPE_CHECKING

from horus.events.types import ProcessKilledEvent
from horus.network.listener import ANY_ADDRESS, Listener
from horus.session.user import UserRole

if TYPE_CHECKING:
    from horus.events.bus import EventBus
    from horus.processes.processTable import ProcessTable

WELL_KNOWN_MAX = 1023                  # ports up to here are reserved for privileged users (ADMIN/ROOT)
EPHEMERAL_PORTS = range(49152, 65536)  # handed out for the local end of outgoing connections


class PortError(Exception):
    """Base for everything PortTable.add() can refuse."""


class PortInUseError(PortError):
    def __init__(self, listener: Listener, holder: Listener) -> None:
        self.listener = listener
        self.holder = holder
        super().__init__(f"{listener.protocol}/{listener.port} on {listener.address} is already in use "
                         f"by '{holder.service}' (PID {holder.pid}) on {holder.address}")


class PortAccessDeniedError(PortError):
    def __init__(self, listener: Listener) -> None:
        self.listener = listener
        super().__init__(f"binding {listener.protocol}/{listener.port} needs admin rights "
                         f"(ports up to {WELL_KNOWN_MAX} are privileged)")


class NoSuchProcessError(PortError):
    def __init__(self, pid: int) -> None:
        self.pid = pid
        super().__init__(f"no such process: {pid}")


class PortTable:
    """Every listening port, keyed by (protocol, address, port) -- so TCP
    and UDP on the same number, or the same port on two different
    interfaces' IPs, are separate entries. One bound to ANY_ADDRESS covers
    every interface and so conflicts with any other binding of that
    protocol/port.

    `process_table`, if given, lets add() refuse ports for processes that
    don't exist. `events`, if given, frees a process's ports as soon as it
    dies (kill, OOM, memory error, ...) via ProcessKilledEvent."""

    def __init__(self, process_table: "ProcessTable | None" = None, events: "EventBus | None" = None) -> None:
        self._listeners: dict[tuple[str, str, int], Listener] = {}
        self._process_table = process_table
        if events is not None:
            events.subscribe(ProcessKilledEvent, lambda event: self.remove_by_pid(event.pid))

    def add(self, listener: Listener, role: UserRole = UserRole.USER) -> Listener:
        """Opens `listener`'s port. `role` is that of whoever opens it --
        defaults to the least privileged one, so a caller that doesn't pass
        it fails closed. Raises NoSuchProcessError, PortAccessDeniedError or
        PortInUseError (all PortError) if it can't."""
        if self._process_table is not None and self._process_table.get_process(listener.pid) is None:
            raise NoSuchProcessError(listener.pid)
        if listener.port <= WELL_KNOWN_MAX and role < UserRole.ADMIN:
            raise PortAccessDeniedError(listener)
        holder = self._conflicting(listener.protocol, listener.port, listener.address)
        if holder is not None:
            raise PortInUseError(listener, holder)
        self._listeners[self._key(listener.protocol, listener.address, listener.port)] = listener
        return listener

    def remove(self, protocol: str, port: int, address: str = ANY_ADDRESS) -> bool:
        """Closes one port. Returns whether it was open."""
        return self._listeners.pop(self._key(protocol, address, port), None) is not None

    def remove_by_pid(self, pid: int) -> list[Listener]:
        """Closes every port of process `pid` -- e.g. because it died.
        Returns what was closed."""
        closed = [listener for listener in self._listeners.values() if listener.pid == pid]
        for listener in closed:
            del self._listeners[self._key(listener.protocol, listener.address, listener.port)]
        return closed

    def find(self, protocol: str, port: int, address: str) -> Listener | None:
        """Who receives `protocol`/`port` arriving at `address` (an
        interface's IP): a listener bound to exactly that address, else one
        bound to every interface."""
        return (self._listeners.get(self._key(protocol, address, port))
                or self._listeners.get(self._key(protocol, ANY_ADDRESS, port)))

    def is_open(self, protocol: str, port: int, address: str = ANY_ADDRESS) -> bool:
        return self.find(protocol, port, address) is not None

    def is_free(self, protocol: str, port: int, address: str = ANY_ADDRESS) -> bool:
        """Whether binding `protocol`/`port` on `address` wouldn't conflict."""
        return self._conflicting(protocol, port, address) is None

    def list(self, protocol: str | None = None) -> list[Listener]:
        """A copy of the open ports, sorted by port -- optionally only one
        protocol's."""
        listeners = [listener for listener in self._listeners.values()
                     if protocol is None or listener.protocol == protocol]
        return sorted(listeners, key=lambda listener: (listener.port, listener.protocol, listener.address))

    def allocate_ephemeral(self, protocol: str, address: str = ANY_ADDRESS) -> int:
        """A free port for the local end of an outgoing connection. Raises
        PortError if every ephemeral port is taken."""
        for port in EPHEMERAL_PORTS:
            if self.is_free(protocol, port, address):
                return port
        raise PortError(f"no free ephemeral {protocol} port left")

    def __len__(self) -> int:
        return len(self._listeners)

    def _conflicting(self, protocol: str, port: int, address: str) -> Listener | None:
        """An existing listener the binding would clash with: same protocol
        and port, and either the same address or one side bound to all
        interfaces."""
        for listener in self._listeners.values():
            if listener.protocol == protocol and listener.port == port and (
                    listener.address == address or ANY_ADDRESS in (listener.address, address)):
                return listener
        return None

    @staticmethod
    def _key(protocol: str, address: str, port: int) -> tuple[str, str, int]:
        return protocol, address, port
