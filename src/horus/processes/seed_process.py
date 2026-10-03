from horus.processes.process import process
from horus.processes.processTable import ProcessTable

# The processes a freshly booted system runs -- (name, owner, cpu_mhz,
# mem_kb, volatility, critical, memory_strings). Background daemons barely
# move (low volatility), the interactive shell fluctuates noticeably more.
# Critical ones crash the system when killed (see cmd_proc.kill).
# memory_strings show up in 'memdump' -- the hook for story clues that only
# ever live in a running process's memory.
_SYSTEM_PROCESSES = [
    ("init", "root", 80.0, 1024, 0.2, True,
     ["/sbin/init", "runlevel=3", "console=tty0"]),
    ("kthreadd", "root", 15.0, 512, 0.3, True,       # parent of all kernel threads
     ["[kthreadd]", "sched=rr", "workers=8"]),
    ("syslogd", "root", 10.0, 768, 0.4, False,       # collects system messages
     ["/var/log/messages", "facility=kern", "level=warning"]),
    ("crond", "root", 5.0, 512, 0.3, False,          # runs scheduled jobs
     ["/etc/crontab", "*/5 * * * * /sbin/vfsd --sync"]),
    ("devd", "root", 8.0, 640, 0.3, False,           # detects drives and devices
     ["SATA A: System Drive", "SATA B: M.1", "SATA C: M.2"]),
    ("netd", "root", 25.0, 1536, 0.6, False,         # network interface eth0
     ["iface=eth0", "addr=10.0.0.2", "gateway=10.0.0.1"]),
    ("vfsd", "root", 20.0, 2048, 0.5, False,         # filesystem cache and sync
     ["mount / (system)", "mount /mnt/m1", "mount /mnt/m2"]),
    ("thermald", "root", 12.0, 384, 0.3, False,      # watches temperature, drives cooling
     ["coolant=WATER", "warn=80C", "crit=90C"]),
    ("powerd", "root", 6.0, 384, 0.2, False,         # watches the PSU budget
     ["psu=Horus PSU", "budget=500W"]),
    ("bash", "user1", 20.0, 2048, 1.0, False,        # the interactive login shell
     ["HOME=/system/root", "SHELL=/bin/bash", "TERM=horus-vt220"]),
]


def seed_processes(process_table: ProcessTable) -> None:
    """Seed the process table with the basic system processes."""
    for name, owner, cpu_mhz, mem_kb, volatility, critical, memory_strings in _SYSTEM_PROCESSES:
        process_table.add_process(process(name=name, pid=0, owner=owner, cpu_mhz=cpu_mhz, mem_kb=mem_kb,
                                          volatility=volatility, critical=critical,
                                          memory_strings=list(memory_strings)))
