"""Shared display helpers for process listings (top/ps): how to sort them
and how to format a process's uptime. Kept separate from ProcessTable itself
since this is presentation logic, not process-management logic -- both
cmd_proc's one-shot renderer and the live TopScreen use it, so sorting/
formatting can't silently drift apart between the two."""

from datetime import datetime

DEFAULT_SORT = "cpu"

# name -> (key function, reverse). cpu/mem: highest first. pid/name: ascending.
# time: oldest started_at (i.e. longest-running) first.
SORT_KEYS = {
    "cpu": (lambda p: p.cpu_mhz, True),
    "mem": (lambda p: p.mem_kb, True),
    "pid": (lambda p: p.pid, False),
    "name": (lambda p: p.name.lower(), False),
    "time": (lambda p: p.started_at, False),
}


def sort_processes(processes: list, sort_by: str = DEFAULT_SORT) -> list:
    """Returns a new list of `processes` sorted by `sort_by` (a key from
    SORT_KEYS). Falls back to the default (cpu) for an unrecognized key
    rather than raising -- callers only ever pass a value that already went
    through argparse's own `choices=`, which rejects anything else first."""
    key, reverse = SORT_KEYS.get(sort_by, SORT_KEYS[DEFAULT_SORT])
    return sorted(processes, key=key, reverse=reverse)


def format_uptime(started_at: datetime, now: datetime | None = None) -> str:
    """Formats how long a process has been running as MM:SS, switching to
    H:MM:SS once it's been running an hour or more."""
    now = now if now is not None else datetime.now()
    total_seconds = max(0, int((now - started_at).total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_system_summary(process_table) -> str:
    """One-line summary of combined resource usage across every process
    currently tracked by `process_table`, for the header of top/ps. Always
    within budget -- ProcessTable._enforce_resource_caps() guarantees the
    combined cpu/mem usage reported here never exceeds the table's
    total_cpu_mhz or total_memory_kb (normally read from HardwareSpec)."""
    used_cpu = process_table.used_cpu_mhz()
    cpu_capacity = process_table.total_cpu_mhz
    cpu_percent = (used_cpu / cpu_capacity * 100) if cpu_capacity else 0.0

    used_mem = process_table.used_mem_kb()
    mem_capacity = process_table.total_memory_kb
    mem_percent = (used_mem / mem_capacity * 100) if mem_capacity else 0.0

    return (f"System: CPU {used_cpu:.0f}/{cpu_capacity} MHz ({cpu_percent:.1f}%)   "
            f"MEM {used_mem}/{mem_capacity} KB ({mem_percent:.1f}%)")
