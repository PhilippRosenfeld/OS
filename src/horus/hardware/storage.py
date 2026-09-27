class Storage:
    def __init__(self, name: str, size: int, manufacturer: str, power_usage_watts: int,
                 power_usage_watts_idle: int | None = None,
                 read_speed_kbps: int = 1200, write_speed_kbps: int = 800):
        self.name = name
        self.size = size
        self.data = bytearray(size)
        self.manufacturer = manufacturer
        self.power_usage_watts = power_usage_watts  # max draw, at full read/write activity
        # draw while idle -- defaults to the max, i.e. a flat draw regardless of activity
        self.power_usage_watts_idle = power_usage_watts if power_usage_watts_idle is None else power_usage_watts_idle
        self.read_speed_kbps = read_speed_kbps    # max read throughput, in KB/s
        self.write_speed_kbps = write_speed_kbps  # max write throughput, in KB/s
        self.read_load = 0.0   # current read utilization: 0.0 (idle) to 1.0 (saturated)
        self.write_load = 0.0  # same, for writes

    @property
    def read_kbps(self) -> float:
        """Current read throughput in KB/s -- read_load of read_speed_kbps."""
        return max(0.0, min(1.0, self.read_load)) * self.read_speed_kbps

    @property
    def write_kbps(self) -> float:
        """Current write throughput in KB/s -- write_load of write_speed_kbps."""
        return max(0.0, min(1.0, self.write_load)) * self.write_speed_kbps

    def calc_current_power_usage(self) -> int:
        """Linear interpolation between idle and max draw, driven by
        whichever of read/write is busier -- same idea as Cpu/Ram's `load`."""
        activity = max(0.0, min(1.0, max(self.read_load, self.write_load)))
        return round(self.power_usage_watts_idle + (self.power_usage_watts - self.power_usage_watts_idle) * activity)

    def to_dict(self) -> dict:
        """Persists the spec only -- data (bytearray of simulated storage
        content) and read/write load (resynced every tick) are excluded."""
        return {
            "name": self.name,
            "size": self.size,
            "manufacturer": self.manufacturer,
            "power_usage_watts": self.power_usage_watts,
            "power_usage_watts_idle": self.power_usage_watts_idle,
            "read_speed_kbps": self.read_speed_kbps,
            "write_speed_kbps": self.write_speed_kbps,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Storage":
        return cls(**data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Storage) and self.to_dict() == other.to_dict()
