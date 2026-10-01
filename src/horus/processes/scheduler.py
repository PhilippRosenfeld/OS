"""Pins every process to exactly one CPU core and simulates what each core
is doing from tick to tick -- the bridge between ProcessTable (which only
knows about MHz budgets) and the cores on HardwareSpec's CPUs."""

import random
from typing import TYPE_CHECKING

import pyglet

from horus.processes.memory import MIN_RESIDENT_SPEED

if TYPE_CHECKING:
    from horus.hardware.spec import HardwareSpec
    from horus.processes.processTable import ProcessTable


class CpuScheduler:
    """Every tick:

    1. syncs the ProcessTable's CPU capacity with the hardware (enabled
       cores only, at their overclocked clock -- see Cpu.effective_mhz), so
       disabling a core or overclocking takes effect on the budget;
    2. pins every process that has no valid core yet (new, or its core got
       disabled) to the least loaded enabled core -- a process always runs
       on exactly one core, never spread across several;
    3. adds the CPU time each process used since the last tick (dt scaled
       by the share of its core's clock it uses, slowed down by however much
       of it is swapped out and sped up by faster memory -- see
       processes.memory) to process.cpu_time;
    4. decides per core whether it's working right now -- with probability
       equal to its load, so a lightly used core mostly idles in standby and
       a busy one is almost always working -- and if so, on which of its
       pinned processes (weighted by how much CPU each one uses) -- and
       appends that state to the core's history (see CpuCore.history)."""

    def __init__(self, process_table: "ProcessTable", hardware: "HardwareSpec",
                 interval: float = 0.5, rng: random.Random | None = None) -> None:
        self._table = process_table
        self._hardware = hardware
        self._interval = interval
        self._rng = rng if rng is not None else random.Random()

    def start(self) -> None:
        self.tick(0.0)
        pyglet.clock.schedule_interval(self.tick, self._interval)

    def stop(self) -> None:
        pyglet.clock.unschedule(self.tick)

    def set_core_enabled(self, core_number: int, enabled: bool) -> bool:
        """Enables/disables one core by its system-wide number. The last
        enabled core can't be disabled -- something has to keep running the
        system. Returns whether the change was applied; the processes on a
        disabled core move to another one right away."""
        cores = self._hardware.installed_cores()
        if not 0 <= core_number < len(cores):
            return False
        core = cores[core_number][1]
        if not enabled and core.enabled and sum(c.enabled for _, c in cores) <= 1:
            return False
        core.enabled = enabled
        if not enabled:
            core.working = False
            core.current_pid = None
        self.tick(0.0)
        return True

    def set_overclock(self, overclock: float) -> None:
        """Sets the same overclock on every installed CPU (and so every core)."""
        for cpu in self._hardware.installed_cpus():
            cpu.set_overclock(overclock)
        self.tick(0.0)

    def tick(self, dt: float) -> None:
        cores = self._hardware.installed_cores()
        capacities = {n: cpu.effective_mhz for n, (cpu, core) in enumerate(cores) if core.enabled}
        self._assign_cores(capacities)
        self._table.set_cpu_capacity(round(sum(capacities.values())), capacities)

        processes = self._table.list_processes()
        memory_speed = self._hardware.memory_speed_factor()
        for proc in processes:
            capacity = capacities.get(proc.core)
            if capacity:
                # swapped-out memory stalls a process (it waits on the disk), faster RAM speeds it up
                speed = max(MIN_RESIDENT_SPEED, proc.resident_share) * memory_speed
                proc.cpu_time += dt * min(1.0, proc.cpu_mhz / capacity) * speed

        for number, (cpu, core) in enumerate(cores):
            pinned = [proc for proc in processes if proc.core == number]
            capacity = capacities.get(number, 0.0)
            core.load = min(1.0, sum(proc.cpu_mhz for proc in pinned) / capacity) if capacity else 0.0
            core.working = core.enabled and bool(pinned) and self._rng.random() < core.load
            core.current_pid = self._pick_running(pinned) if core.working else None
            if dt > 0:  # only real ticks -- not the immediate re-sync after a toggle/overclock
                core.history.append(core.state)

    def _assign_cores(self, capacities: dict[int, float]) -> None:
        """Pins unscheduled processes (and ones whose core is gone or
        disabled) to whichever enabled core has the most headroom left,
        in PID order so the outcome is deterministic."""
        if not capacities:
            for proc in self._table.list_processes():
                proc.core = None
            return
        used = {number: 0.0 for number in capacities}
        processes = sorted(self._table.list_processes(), key=lambda p: p.pid)
        for proc in processes:
            if proc.core in capacities:
                used[proc.core] += proc.cpu_mhz
        for proc in processes:
            if proc.core in capacities:
                continue
            proc.core = min(capacities, key=lambda n: (used[n] / capacities[n], n))
            used[proc.core] += proc.cpu_mhz

    def _pick_running(self, pinned: list) -> int | None:
        weights = [max(proc.cpu_mhz, 0.0) for proc in pinned]
        if not pinned or sum(weights) <= 0:
            return None
        return self._rng.choices(pinned, weights=weights)[0].pid
