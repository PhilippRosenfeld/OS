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

    def __post_init__(self) -> None:
        if self.baseline_cpu_mhz is None:
            self.baseline_cpu_mhz = self.cpu_mhz
        if self.baseline_mem_kb is None:
            self.baseline_mem_kb = self.mem_kb