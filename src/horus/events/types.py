from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Event:
    timestamp: datetime = field(default_factory=datetime.now, kw_only=True)

@dataclass(frozen=True)
class CommandExecutedEvent(Event):
    command: str
    args: list[str]
    user: str
    session_id: str

@dataclass(frozen=True)
class FileReadEvent(Event):
    path: str
    user: str
    session_id: str
    
@dataclass(frozen=True)
class FileWrittenEvent(Event):
    path: str
    user: str
    session_id: str
    bytes_written: int
    
@dataclass(frozen=True)
class LoginAttemptEvent(Event):
    user: str
    session_id: str
    
@dataclass(frozen=True)
class ProcessStartedEvent(Event):
    pid: int
    name: str
    owner: str

@dataclass(frozen=True)
class ProcessKilledEvent(Event):
    pid: int
    name: str
    killed_by: str
    critical: bool = False  # was this a system-critical process (e.g. init)?
                             # subscribers use this to react to a system-wide
                             # crash regardless of what killed it -- see
                             # processes.system_reactions
