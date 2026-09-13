class Cpu:
    def __init__(self, name: str, cores: int, mhz: int, power_usage_watts_max: int, power_usage_watts_min: int, manufacturer: str):
        self.name = name
        self.cores = cores
        self.mhz = mhz
        self.power_usage_watts_max = power_usage_watts_max
        self.power_usage_watts_min = power_usage_watts_min
        self.manufacturer = manufacturer
        self.load = 0.0  # current utilization: 0.0 (idle) to 1.0 (fully loaded)

    def calc_current_power_usage(self) -> int:
        """Linear interpolation between idle and max draw based on self.load --
        0.0 load draws power_usage_watts_min, 1.0 load draws power_usage_watts_max."""
        load = max(0.0, min(1.0, self.load))
        return round(self.power_usage_watts_min + (self.power_usage_watts_max - self.power_usage_watts_min) * load)

    def to_dict(self) -> dict:
        """Persists the spec only -- registers (runtime CPU state) and load
        (resynced from the live ProcessTable every tick) are excluded."""
        return {
            "name": self.name,
            "cores": self.cores,
            "mhz": self.mhz,
            "power_usage_watts_max": self.power_usage_watts_max,
            "power_usage_watts_min": self.power_usage_watts_min,
            "manufacturer": self.manufacturer,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Cpu":
        return cls(**data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Cpu) and self.to_dict() == other.to_dict()