from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class LogSeverity(Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class SystemLogEntry:
    timestamp: datetime
    severity: LogSeverity
    message: str


class SystemLog:
    """Fixed-size rolling log of system-wide warnings/errors (power
    overloads, critical process crashes, ...) for the 'err' command's log
    viewer. Fed by register_system_log() (see processes.system_reactions),
    kept independent of whatever else reacts to the same events (sounds,
    CrashScreen, ...) so it works regardless of what else is wired up.
    Oldest entries are dropped once `maxlen` is reached, so memory stays
    bounded no matter how long the session runs."""

    def __init__(self, maxlen: int = 200) -> None:
        self._entries: deque[SystemLogEntry] = deque(maxlen=maxlen)

    def warning(self, message: str) -> None:
        self._log(LogSeverity.WARNING, message)

    def error(self, message: str) -> None:
        self._log(LogSeverity.ERROR, message)

    def _log(self, severity: LogSeverity, message: str) -> None:
        self._entries.append(SystemLogEntry(timestamp=datetime.now(), severity=severity, message=message))

    def entries(self) -> list[SystemLogEntry]:
        """Oldest first -- matches how the entries were recorded."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
