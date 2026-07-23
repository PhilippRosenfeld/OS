from dataclasses import dataclass, field
from datetime import datetime

@dataclass(frozen=True)
class Event:
    timestamp: datetime = field(default_factory=datetime.now)

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
