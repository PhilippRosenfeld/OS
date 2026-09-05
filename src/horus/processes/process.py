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
    volatility: float = 1.0  # scales how strongly this process's cpu/mem drift per
                              # ProcessTable._fluctuate() tick -- 0 = never moves,
                              # 1 = normal, >1 = jumpier than normal
    critical: bool = False   # e.g. init (PID 1): killing it is allowed (permissions
                              # permitting) but crashes the whole system -- see
                              # cmd_proc.kill(), which warns and asks for confirmation
                              # first