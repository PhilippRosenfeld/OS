RAM_OVERCLOCK_MIN = 1.0   # stock memory clock
RAM_OVERCLOCK_MAX = 1.4   # +40% -- the modules aren't rated past this
RAM_OVERCLOCK_STEP = 0.1

# timings preset -> (speed factor, instability factor). Tighter timings make
# memory a bit faster but multiply the chance of errors once it's
# overclocked or hot (see processes.memory.MemoryManager); relaxed ones
# trade a little speed for stability.
RAM_TIMINGS: dict[str, tuple[float, float]] = {
    "Relaxed": (0.95, 0.5),
    "Standard": (1.0, 1.0),
    "Tight": (1.05, 2.5),
    "Extreme": (1.1, 6.0),
}
DEFAULT_RAM_TIMINGS = "Standard"


class Ram:
    def __init__(self, name: str, size: int, manufacturer: str, power_usage_watts_min: int, power_usage_watts_max: int,
                 enabled: bool = True, overclock: float = RAM_OVERCLOCK_MIN, timings: str = DEFAULT_RAM_TIMINGS):
        self.name = name
        self.size = size
        self.data = bytearray(size)
        self.manufacturer = manufacturer
        self.power_usage_watts_min = power_usage_watts_min
        self.power_usage_watts_max = power_usage_watts_max
        self.enabled = enabled      # a disabled module adds no capacity and draws nothing
        self.overclock = overclock  # memory clock multiplier, RAM_OVERCLOCK_MIN..RAM_OVERCLOCK_MAX
        self.timings = timings if timings in RAM_TIMINGS else DEFAULT_RAM_TIMINGS
        self.load = 0.0  # current utilization: 0.0 (idle) to 1.0 (fully loaded)

    def set_overclock(self, overclock: float) -> None:
        self.overclock = round(max(RAM_OVERCLOCK_MIN, min(RAM_OVERCLOCK_MAX, overclock)), 2)

    @property
    def speed_factor(self) -> float:
        """How much faster than stock this module makes the work done in it:
        half of the overclock carries over into speed, times the timings'."""
        return (1.0 + (self.overclock - 1.0) * 0.5) * RAM_TIMINGS[self.timings][0]

    @property
    def instability(self) -> float:
        """Relative chance of memory errors from the settings alone -- 0 at
        stock clock, growing with overclock and with tighter timings."""
        return (self.overclock - 1.0) * RAM_TIMINGS[self.timings][1]

    def calc_current_power_usage(self) -> int:
        """Linear interpolation between idle and max draw based on self.load --
        0.0 load draws power_usage_watts_min, 1.0 load draws power_usage_watts_max
        -- scaled by overclock squared (a higher clock needs a higher voltage).
        A disabled module draws nothing."""
        if not self.enabled:
            return 0
        load = max(0.0, min(1.0, self.load))
        draw = self.power_usage_watts_min + (self.power_usage_watts_max - self.power_usage_watts_min) * load
        return round(draw * self.overclock ** 2)

    def to_dict(self) -> dict:
        """Persists the spec only -- data (bytearray of simulated memory
        content) and load (resynced every tick) are excluded."""
        return {
            "name": self.name,
            "size": self.size,
            "manufacturer": self.manufacturer,
            "power_usage_watts_min": self.power_usage_watts_min,
            "power_usage_watts_max": self.power_usage_watts_max,
            "enabled": self.enabled,
            "overclock": self.overclock,
            "timings": self.timings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Ram":
        return cls(**data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Ram) and self.to_dict() == other.to_dict()
