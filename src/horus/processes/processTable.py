import random
from typing import TYPE_CHECKING

import pyglet

from horus.events.types import ProcessKilledEvent, ProcessStartedEvent
from horus.processes.process import process
from horus.session.user import UserRole

if TYPE_CHECKING:
    from horus.events.bus import EventBus

_CPU_STEP = 1.5      # max percentage points a process's cpu_percent drifts per tick
_MEM_STEP = 48        # max KB a process's mem_kb drifts per tick
_MIN_MEM_KB = 128     # floor so a process never looks like it's using ~0 memory

class ProcessTable:
    def __init__(self, fluctuation_interval: float = 1.0, events: "EventBus | None" = None):
        self.processes: dict[int, process] = {}
        self.next_pid: int = 1
        self._fluctuation_interval = fluctuation_interval
        self._events = events  # publishes ProcessStartedEvent/ProcessKilledEvent here so
                                # other systems (story progress, future malware reactions, ...)
                                # can react without add_process/remove_process callers having
                                # to remember to publish anything themselves

    def add_process(self, process: process = None) -> process:
        if process is None:
            raise ValueError("Process cannot be None")
        pid = self.next_pid
        self.next_pid += 1
        process.pid = pid
        new_process = process
        self.processes[pid] = new_process
        if self._events is not None:
            self._events.publish(ProcessStartedEvent(pid=new_process.pid, name=new_process.name, owner=new_process.owner))
        return new_process

    def remove_process(self, pid: int, user: str, role: UserRole = UserRole.USER) -> bool:
        """Kills a process: its own owner may always kill it, ADMIN or ROOT
        may kill anyone's (matching the encrypt/decrypt permission model --
        see filesystem.permissions.can_write_encrypted), a plain USER may not
        kill someone else's. `role` defaults to USER (least-privileged) so
        existing callers that don't pass one fail closed, not open."""
        if pid not in self.processes:
            return False
        proc = self.processes[pid]
        if proc.owner != user and role < UserRole.ADMIN:
            return False
        removed = self.processes.pop(pid)
        if self._events is not None:
            self._events.publish(ProcessKilledEvent(pid=removed.pid, name=removed.name, killed_by=user))
        return True

    def get_process(self, pid: int) -> process | None:
        return self.processes.get(pid)

    def list_processes(self) -> list[process]:
        return list(self.processes.values())

    def start_fluctuating(self) -> None:
        """Makes cpu_percent/mem_kb drift up and down over time via
        pyglet.clock, so 'top'/'ps' don't show frozen, static-looking
        numbers. Call once; safe to call again after stop_fluctuating()."""
        pyglet.clock.schedule_interval(self._fluctuate, self._fluctuation_interval)

    def stop_fluctuating(self) -> None:
        pyglet.clock.unschedule(self._fluctuate)

    def _fluctuate(self, dt: float) -> None:
        for proc in self.processes.values():
            cpu_range = _CPU_STEP * proc.volatility
            mem_range = _MEM_STEP * proc.volatility
            proc.cpu_percent = max(0.0, min(100.0, proc.cpu_percent + random.uniform(-cpu_range, cpu_range)))
            proc.mem_kb = max(_MIN_MEM_KB, proc.mem_kb + round(random.uniform(-mem_range, mem_range)))

    def adjust_load(self, pid: int, cpu_delta: float = 0.0, mem_delta: int = 0) -> None:
        """Nudges one process's cpu_percent/mem_kb by a fixed amount, clamped
        the same way organic fluctuation is. Not called from anywhere yet --
        this is the hook for later work where something other than random
        drift should move the numbers (e.g. an event that spikes a process's
        load when it activates); a positive delta raises usage, negative
        lowers it. No-op if `pid` isn't a currently-tracked process."""
        proc = self.processes.get(pid)
        if proc is None:
            return
        proc.cpu_percent = max(0.0, min(100.0, proc.cpu_percent + cpu_delta))
        proc.mem_kb = max(_MIN_MEM_KB, proc.mem_kb + mem_delta)
        
        