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

@dataclass(frozen=True)
class PowerUsageCheckedEvent(Event):
    """Published every tick of HardwareSpec.start_power_monitoring(), not
    just when crossing the PSU's budget -- subscribers always see current
    state instead of only breach edges."""
    total_power_usage: float
    psu_output_watts: float
    over_budget: bool

@dataclass(frozen=True)
class TemperatureCriticalEvent(Event):
    """Published once when the system's temperature crosses the critical
    threshold, triggering a full thermal shutdown (see HardwareSpec.
    _handle_thermal_shutdown) -- no process is singled out or killed, the
    whole system goes down. Subscribers can react to this event by playing
    a sound, showing a crash screen, etc."""
    temperature: float
    critical_temperature: float
    
@dataclass(frozen=True)
class TemperatureWarningEvent(Event):
    """Published every tick of HardwareSpec.start_power_monitoring(), not
    just when crossing the warning threshold -- mirrors PowerUsageCheckedEvent's
    over_budget so subscribers always see current state instead of only
    breach edges (e.g. so a status-bar light can auto-clear once the
    temperature drops back down, not just latch forever)."""
    temperature: float
    critical_temperature: float
    over_warning: bool