from dataclasses import dataclass, field
from pathlib import Path
import json

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