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
    "cpu": (lambda p: p.cpu_percent, True),
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
