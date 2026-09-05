import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HardwareSpec:
    """The simulated machine's hardware configuration."""

    memory_kb: str = "65536K"
    memory_count: int = 2
    cpu_mhz: int = 3200
    cpu_cores: int = 1
    cpu_name: str = "Coeles X3201"
    coolant_type: str = "Water"
    coolant_amount: int = 99

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "HardwareSpec":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def total_memory_kb(self) -> int:
        """Total simulated RAM in KB: memory_kb (e.g. '65536K', per module)
        times memory_count modules -- matches how the boot sequence displays
        it ('{memory_count} x {memory_size}')."""
        digits = "".join(ch for ch in self.memory_kb if ch.isdigit())
        per_module_kb = int(digits) if digits else 0
        return per_module_kb * self.memory_count

    def total_cpu_mhz(self) -> int:
        """Total simulated CPU capacity in MHz across all cores -- matches
        how the boot sequence displays it ('{cpu_cores} @ {cpu_mhz}')."""
        return self.cpu_mhz * self.cpu_cores