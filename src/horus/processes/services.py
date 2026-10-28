from dataclasses import dataclass

from horus.network.listener import Listener
from horus.network.port_table import PortError, PortTable
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable
from horus.session.user import UserRole


@dataclass(frozen=True)
class SystemProcess:
    """Blueprint of a process a freshly booted system runs -- seed_processes()
    starts a real (mutable) process from it. Frozen: the blueprint itself
    never changes, only the processes started from it do."""
    name: str
    owner: str
    cpu_mhz: float
    mem_kb: int
    volatility: float
    critical: bool
    memory_strings: tuple[str, ...]                 # show up in 'memdump'
    ports: tuple[tuple[str, int, str], ...] = ()    # (protocol, port, service) the process listens on


_SYSTEM_PROCESSES = [
    SystemProcess(name="init", owner="root", cpu_mhz=80.0, mem_kb=1024, volatility=0.2, critical=True, memory_strings=("/sbin/init", "runlevel=3", "console=tty0")),
    SystemProcess(name="kthreadd", owner="root", cpu_mhz=15.0, mem_kb=512, volatility=0.3, critical=True, memory_strings=("[kthreadd]", "sched=rr", "workers=8")),
    SystemProcess(name="syslogd", owner="root", cpu_mhz=10.0, mem_kb=768, volatility=0.4, critical=False, memory_strings=("/var/log/messages", "facility=kern", "level=warning"), ports=(("udp", 514, "syslog"),)),
    SystemProcess(name="crond", owner="root", cpu_mhz=5.0, mem_kb=512, volatility=0.3, critical=False, memory_strings=("/etc/crontab", "*/5 * * * * /sbin/vfsd --sync")),
    SystemProcess(name="devd", owner="root", cpu_mhz=8.0, mem_kb=640, volatility=0.3, critical=False, memory_strings=("SATA A: System Drive", "SATA B: M.1", "SATA C: M.2")),
    SystemProcess(name="netd", owner="root", cpu_mhz=25.0, mem_kb=1536, volatility=0.6, critical=False, memory_strings=("iface=eth0", "addr=10.0.0.2", "gateway=10.0.0.1"), ports=(("udp", 53, "dns"),)),
    SystemProcess(name="vfsd", owner="root", cpu_mhz=20.0, mem_kb=2048, volatility=0.5, critical=False, memory_strings=("mount / (system)", "mount /mnt/m1", "mount /mnt/m2")),
    SystemProcess(name="thermald", owner="root", cpu_mhz=12.0, mem_kb=384, volatility=0.3, critical=False, memory_strings=("coolant=WATER", "warn=80C", "crit=90C")),
    SystemProcess(name="powerd", owner="root", cpu_mhz=6.0, mem_kb=384, volatility=0.2, critical=False, memory_strings=("psu=Horus PSU", "budget=500W")),
    SystemProcess(name="bash", owner="user1", cpu_mhz=20.0, mem_kb=2048, volatility=1.0, critical=False, memory_strings=("HOME=/system/root", "SHELL=/bin/bash", "TERM=horus-vt220")),
]

def find_service(name: str) -> SystemProcess | None:
    """Returns the SystemProcess with the given name, or None if not found."""
    return next((s for s in _SYSTEM_PROCESSES if s.name == name), None)

def start_service(spec, process_table: ProcessTable, port_table: PortTable | None = None):
    proc = process_table.add_process(Process(name=spec.name, pid=0, owner=spec.owner, cpu_mhz=spec.cpu_mhz,
                                             mem_kb=spec.mem_kb, volatility=spec.volatility,
                                             critical=spec.critical, memory_strings=list(spec.memory_strings)))
    if port_table is not None:
        role = UserRole.ROOT if spec.owner == "root" else UserRole.USER
        try:
           for protocol, port, service in spec.ports:
               port_table.add(Listener(protocol, port, pid=proc.pid, service=service), role=role)
        except PortError:
            process_table.remove_process(proc.pid, user="root", role=UserRole.ROOT)
            raise
    return proc
    

def seed_processes(process_table: ProcessTable, port_table: PortTable | None = None) -> None:
    """Starts the basic system processes, and -- given a port_table -- opens
    the ports each of them listens on. A port that can't be opened means the
    list above is wrong, so that's left to fail loudly at startup."""
    for spec in _SYSTEM_PROCESSES:
        start_service(spec, process_table, port_table)
