from dataclasses import dataclass, field
from pathlib import Path
import json


@dataclass
class BootProgress:
    disks: dict[str, bool] = field(default_factory=dict)

    def status(self, disk_id: str) -> str:
        return "OK" if self.disks.get(disk_id, False) else "FAILED"

    def mark_ok(self, disk_id: str) -> None:
        self.disks[disk_id] = True

    def mark_failed(self, disk_id: str) -> None:
        self.disks[disk_id] = False

    def latest_ok_disk(self, disk_count: int = 3, sectors_per_disk: int = 3) -> int | None:
        """Returns the highest disk number whose every sector is OK, or
        None if not even disk 1 is fully OK yet."""
        latest = None
        for disk in range(1, disk_count + 1):
            all_ok = all(
                self.disks.get(f"disk{disk}_{sector}", False)
                for sector in range(1, sectors_per_disk + 1)
            )
            if all_ok:
                latest = disk
            else:
                break   # disks load in order -- stop at the first incomplete one
        return latest

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.disks, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BootProgress":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(disks=data)