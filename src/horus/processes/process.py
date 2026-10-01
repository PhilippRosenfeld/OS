from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class process:
    name:str
    pid: int
    owner: str = "root"
    started_at: datetime = field(default_factory=datetime.now)
    cpu_mhz: float = 0.0  # absolute cpu usage, not a percentage -- see
                          # ProcessTable.total_cpu_mhz for the system's capacity
    mem_kb: int = 0
    killable: bool = True
    volatility: float = 1.0  # scales how far this process's cpu/mem can stray from
                              # its baseline per ProcessTable._fluctuate() tick (it's a
                              # Gaussian stddev there, not a uniform range) -- 0 = never
                              # moves, 1 = normal, >1 = jumpier than normal
    critical: bool = False   # e.g. init (PID 1): killing it is allowed (permissions
                              # permitting) but crashes the whole system -- see
                              # cmd_proc.kill(), which warns and asks for confirmation
                              # first
    baseline_cpu_mhz: float | None = None  # the value cpu_mhz fluctuates around --
                                            # defaults to this process's own starting
                                            # cpu_mhz (see __post_init__) so existing
                                            # callers don't need to pass it explicitly
    baseline_mem_kb: float | None = None   # same, for mem_kb
    core: int | None = None  # system-wide core number this process is pinned to (see
                              # HardwareSpec.installed_cores) -- always exactly one core,
                              # chosen by CpuScheduler; None = not scheduled (yet)
    cpu_time: float = 0.0    # seconds of CPU actually spent on this process so far --
                              # a process using half its core's clock for 10s has 5s
    swapped_kb: int = 0      # part of mem_kb paged out to swap instead of held in RAM
                              # (see processes.memory.MemoryManager) -- slows the process down
    memory_strings: list[str] = field(default_factory=list)  # text that shows up in this process's
                                                              # memory dump ('memdump') -- e.g. story
                                                              # clues only ever held in RAM

    @property
    def resident_share(self) -> float:
        """Share of the process's memory actually in RAM, 0.0-1.0."""
        return 1.0 - (self.swapped_kb / self.mem_kb) if self.mem_kb > 0 else 1.0

    def __post_init__(self) -> None:
        if self.baseline_cpu_mhz is None:
            self.baseline_cpu_mhz = self.cpu_mhz
        if self.baseline_mem_kb is None:
            self.baseline_mem_kb = self.mem_kb