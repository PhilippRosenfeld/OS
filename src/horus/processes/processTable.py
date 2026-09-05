import random
from typing import TYPE_CHECKING

import pyglet

from horus.events.types import ProcessKilledEvent, ProcessStartedEvent
from horus.processes.process import process
from horus.session.user import UserRole

if TYPE_CHECKING:
    from horus.events.bus import EventBus

_CPU_STEP_MHZ = 40    # max MHz a process's cpu_mhz drifts per tick
_MEM_STEP = 48        # max KB a process's mem_kb drifts per tick
_MIN_MEM_KB = 128     # floor so a process never looks like it's using ~0 memory
DEFAULT_TOTAL_CPU_MHZ = 3200        # matches HardwareSpec's own default (cpu_mhz=3200, cpu_cores=1)
DEFAULT_TOTAL_MEMORY_KB = 8 * 1024 * 1024  # 8 GiB -- used if no real HardwareSpec is wired in

class ProcessTable:
    def __init__(self, fluctuation_interval: float = 1.0, events: "EventBus | None" = None,
                 total_memory_kb: int = DEFAULT_TOTAL_MEMORY_KB, total_cpu_mhz: int = DEFAULT_TOTAL_CPU_MHZ):
        self.processes: dict[int, process] = {}
        self.next_pid: int = 1
        self._fluctuation_interval = fluctuation_interval
        self._events = events  # publishes ProcessStartedEvent/ProcessKilledEvent here so
                                # other systems (story progress, future malware reactions, ...)
                                # can react without add_process/remove_process callers having
                                # to remember to publish anything themselves
        self.total_memory_kb = total_memory_kb  # combined mem_kb across all processes is
                                                 # kept at or below this -- see _enforce_resource_caps
        self.total_cpu_mhz = total_cpu_mhz      # same, but for combined cpu_mhz. Both are normally
                                                 # HardwareSpec.total_memory_kb()/total_cpu_mhz() --
                                                 # passed in rather than looked up here so ProcessTable
                                                 # doesn't need to know HardwareSpec exists

    def add_process(self, process: process = None) -> process:
        if process is None:
            raise ValueError("Process cannot be None")
        pid = self.next_pid
        self.next_pid += 1
        process.pid = pid
        new_process = process
        self.processes[pid] = new_process
        self._enforce_resource_caps()
        if self._events is not None:
            self._events.publish(ProcessStartedEvent(pid=new_process.pid, name=new_process.name, owner=new_process.owner))
        return new_process

    def can_kill(self, pid: int, user: str, role: UserRole = UserRole.USER) -> bool:
        """Read-only permission check, split out from remove_process() so a
        caller (e.g. kill's confirmation prompt for a critical process) can
        check authorization before actually acting on it. Its own owner may
        always kill a process, ADMIN or ROOT may kill anyone's (matching the
        encrypt/decrypt permission model -- see
        filesystem.permissions.can_write_encrypted), a plain USER may not
        kill someone else's. `role` defaults to USER (least-privileged) so
        callers that don't pass one fail closed, not open."""
        proc = self.processes.get(pid)
        if proc is None:
            return False
        return proc.owner == user or role >= UserRole.ADMIN

    def remove_process(self, pid: int, user: str, role: UserRole = UserRole.USER) -> bool:
        """Kills a process -- see can_kill() for who's authorized."""
        if not self.can_kill(pid, user, role):
            return False
        removed = self.processes.pop(pid)
        if self._events is not None:
            self._events.publish(ProcessKilledEvent(pid=removed.pid, name=removed.name, killed_by=user, critical=removed.critical))
        return True

    def get_process(self, pid: int) -> process | None:
        return self.processes.get(pid)

    def list_processes(self) -> list[process]:
        return list(self.processes.values())

    def used_cpu_mhz(self) -> float:
        """Combined cpu_mhz across every tracked process -- guaranteed by
        _enforce_resource_caps() to never exceed total_cpu_mhz."""
        return sum(proc.cpu_mhz for proc in self.processes.values())

    def used_mem_kb(self) -> int:
        """Combined mem_kb across every tracked process -- guaranteed by
        _enforce_resource_caps() to never exceed total_memory_kb."""
        return sum(proc.mem_kb for proc in self.processes.values())

    def _enforce_resource_caps(self) -> None:
        """Keeps combined cpu/mem usage within what the system actually has:
        if fluctuation, a newly added process, or adjust_load() pushes the
        total over budget, every process's share is scaled down
        proportionally so the total lands exactly at the cap -- each
        process's usage *relative to the others* is preserved, only the
        overall scale shrinks. This can push an individual process below its
        usual _MIN_MEM_KB floor under heavy combined load; that's expected,
        not a bug -- the system-wide cap takes priority."""
        total_cpu = self.used_cpu_mhz()
        if total_cpu > self.total_cpu_mhz and total_cpu > 0:
            scale = self.total_cpu_mhz / total_cpu
            for proc in self.processes.values():
                proc.cpu_mhz *= scale

        total_mem = self.used_mem_kb()
        if total_mem > self.total_memory_kb and total_mem > 0:
            scale = self.total_memory_kb / total_mem
            for proc in self.processes.values():
                proc.mem_kb = max(1, round(proc.mem_kb * scale))

    def start_fluctuating(self) -> None:
        """Makes cpu_mhz/mem_kb drift up and down over time via
        pyglet.clock, so 'top'/'ps' don't show frozen, static-looking
        numbers. Call once; safe to call again after stop_fluctuating()."""
        pyglet.clock.schedule_interval(self._fluctuate, self._fluctuation_interval)

    def stop_fluctuating(self) -> None:
        pyglet.clock.unschedule(self._fluctuate)

    def _fluctuate(self, dt: float) -> None:
        for proc in self.processes.values():
            cpu_range = _CPU_STEP_MHZ * proc.volatility
            mem_range = _MEM_STEP * proc.volatility
            proc.cpu_mhz = max(0.0, min(self.total_cpu_mhz, proc.cpu_mhz + random.uniform(-cpu_range, cpu_range)))
            proc.mem_kb = max(_MIN_MEM_KB, proc.mem_kb + round(random.uniform(-mem_range, mem_range)))
        self._enforce_resource_caps()

    def adjust_load(self, pid: int, cpu_delta: float = 0.0, mem_delta: int = 0) -> None:
        """Nudges one process's cpu_mhz/mem_kb by a fixed amount, clamped
        the same way organic fluctuation is. Not called from anywhere yet --
        this is the hook for later work where something other than random
        drift should move the numbers (e.g. an event that spikes a process's
        load when it activates); a positive delta raises usage, negative
        lowers it. No-op if `pid` isn't a currently-tracked process."""
        proc = self.processes.get(pid)
        if proc is None:
            return
        proc.cpu_mhz = max(0.0, min(self.total_cpu_mhz, proc.cpu_mhz + cpu_delta))
        proc.mem_kb = max(_MIN_MEM_KB, proc.mem_kb + mem_delta)
        self._enforce_resource_caps()
        
        