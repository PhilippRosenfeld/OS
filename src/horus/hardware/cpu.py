from collections import deque
from enum import Enum

CORE_HISTORY_LENGTH = 360  # samples of each core's state kept -- 3 minutes (the CPU screen's longest
                           # timescale) at the scheduler's 0.5s tick
OVERCLOCK_MIN = 1.0   # stock clock
OVERCLOCK_MAX = 1.5   # +50% -- past this the simulated silicon isn't rated for it
OVERCLOCK_STEP = 0.1


class CoreState(Enum):
    WORKING = "Working"    # enabled, and busy with a process this tick
    STANDBY = "Active"     # enabled, but idle right now
    DISABLED = "Disabled"  # switched off -- runs nothing, adds no capacity


class CpuCore:
    """One core of a Cpu. `enabled` is configuration (persisted via
    Cpu.disabled_cores); `working`/`current_pid` are runtime state the
    CpuScheduler (see processes.scheduler) rewrites every tick."""

    def __init__(self, index: int, enabled: bool = True) -> None:
        self.index = index        # position within its own Cpu, 0-based
        self.enabled = enabled
        self.working = False      # busy with `current_pid` this tick
        self.current_pid: int | None = None
        self.load = 0.0           # share of this core's clock its pinned processes use, 0.0-1.0
        self.history: deque[CoreState] = deque(maxlen=CORE_HISTORY_LENGTH)  # state per scheduler tick, oldest first

    @property
    def state(self) -> CoreState:
        if not self.enabled:
            return CoreState.DISABLED
        return CoreState.WORKING if self.working else CoreState.STANDBY


class Cpu:
    def __init__(self, name: str, cores: int, mhz: int, power_usage_watts_max: int, power_usage_watts_min: int, manufacturer: str,
                 overclock: float = OVERCLOCK_MIN, disabled_cores: list[int] | None = None):
        self.name = name
        self.cores = cores
        self.mhz = mhz  # stock clock per core -- see effective_mhz for the overclocked one
        self.power_usage_watts_max = power_usage_watts_max
        self.power_usage_watts_min = power_usage_watts_min
        self.manufacturer = manufacturer
        self.overclock = overclock  # clock multiplier applied to every core, OVERCLOCK_MIN..OVERCLOCK_MAX
        disabled = set(disabled_cores or [])
        self.core_list = [CpuCore(i, enabled=i not in disabled) for i in range(cores)]

    @property
    def load(self) -> float:
        """Average utilization across the enabled cores, 0.0 (idle) to 1.0
        (fully loaded) -- each core's own `load` is what actually drives its
        draw (see calc_current_power_usage), normally set per core by the
        CpuScheduler."""
        enabled = self.enabled_cores()
        return sum(core.load for core in enabled) / len(enabled) if enabled else 0.0

    @load.setter
    def load(self, value: float) -> None:
        """Spreads one utilization evenly over every enabled core -- for when
        nothing tracks which core does what (no CpuScheduler running)."""
        for core in self.enabled_cores():
            core.load = value

    @property
    def idle_watts_per_core(self) -> float:
        return self.power_usage_watts_min / self.cores if self.cores else 0.0

    @property
    def dynamic_watts_per_core(self) -> float:
        return (self.power_usage_watts_max - self.power_usage_watts_min) / self.cores if self.cores else 0.0

    def core_power_usage(self, core: CpuCore) -> float:
        """One core's draw: nothing at all while disabled; otherwise its
        share of the idle draw -- raised linearly by the overclock, which
        needs a higher voltage even when idle -- plus its share of the
        load-dependent draw, scaled by its own load and by overclock
        squared (a higher clock at a higher voltage costs disproportionately
        more). All of it ends up as heat (see HardwareSpec._update_temperature)."""
        if not core.enabled:
            return 0.0
        load = max(0.0, min(1.0, core.load))
        return (self.idle_watts_per_core * self.overclock
                + self.dynamic_watts_per_core * load * self.overclock ** 2)

    @property
    def effective_mhz(self) -> float:
        """Per-core clock after overclocking."""
        return self.mhz * self.overclock

    def enabled_cores(self) -> list[CpuCore]:
        return [core for core in self.core_list if core.enabled]

    def set_overclock(self, overclock: float) -> None:
        self.overclock = round(max(OVERCLOCK_MIN, min(OVERCLOCK_MAX, overclock)), 2)

    def calc_current_power_usage(self) -> int:
        """Sum of every core's draw (see core_power_usage): disabled cores
        save their share entirely, busy cores draw more than idle ones, and
        overclocking raises both. At stock clock with every core enabled and
        evenly loaded this is a plain linear interpolation between min and
        max draw, same as before cores were modelled individually."""
        return round(sum(self.core_power_usage(core) for core in self.core_list))

    def to_dict(self) -> dict:
        """Persists the spec only -- registers (runtime CPU state), load
        (resynced every tick) and each core's working state are excluded;
        which cores are disabled is kept."""
        return {
            "name": self.name,
            "cores": self.cores,
            "mhz": self.mhz,
            "power_usage_watts_max": self.power_usage_watts_max,
            "power_usage_watts_min": self.power_usage_watts_min,
            "manufacturer": self.manufacturer,
            "overclock": self.overclock,
            "disabled_cores": [core.index for core in self.core_list if not core.enabled],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Cpu":
        return cls(**data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Cpu) and self.to_dict() == other.to_dict()
