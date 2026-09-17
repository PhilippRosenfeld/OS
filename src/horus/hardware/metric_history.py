from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MetricSample:
    timestamp: datetime
    value: float


class MetricHistory:
    """Fixed-size rolling window of recent (timestamp, value) samples for one
    metric -- e.g. total power draw, cooling draw -- feeding a future line
    graph in a component's detail panel (Power/Cooling/Network, opened via
    Enter on the hardware overview). Oldest samples are dropped once `maxlen`
    is reached, so memory stays bounded no matter how long the session runs.
    Not persisted -- this is runtime telemetry, not configuration, so it's
    kept off HardwareSpec's dataclass fields (see HardwareSpec.__post_init__)
    and plays no part in save()/load() or equality."""

    def __init__(self, maxlen: int = 60) -> None:
        self._samples: deque[MetricSample] = deque(maxlen=maxlen)

    def record(self, value: float, timestamp: datetime | None = None) -> None:
        self._samples.append(MetricSample(timestamp=timestamp or datetime.now(), value=value))

    def samples(self) -> list[MetricSample]:
        return list(self._samples)

    def values(self) -> list[float]:
        """Just the values, oldest first -- what a line graph would plot on Y."""
        return [sample.value for sample in self._samples]

    def latest(self) -> float | None:
        return self._samples[-1].value if self._samples else None

    def __len__(self) -> int:
        return len(self._samples)
