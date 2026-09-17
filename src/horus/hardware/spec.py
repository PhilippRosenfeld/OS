import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pyglet

from horus.events.types import PowerUsageCheckedEvent
from horus.hardware.cooling_system import CoolantType, CoolingSystem
from horus.hardware.cpu import Cpu
from horus.hardware.metric_history import MetricHistory
from horus.hardware.motherboard import CpuSocket, Motherboard, RamSlots, StorageSlots
from horus.hardware.network_interface import NetworkInterface
from horus.hardware.power_supply_unit import PowerSupplyUnit
from horus.hardware.ram import Ram
from horus.hardware.storage import Storage

if TYPE_CHECKING:
    # deferred to avoid a hard runtime dependency -- HardwareSpec only needs
    # these for start_power_monitoring(), and stays agnostic otherwise,
    # mirroring how ProcessTable stays agnostic of HardwareSpec's existence
    from horus.events.bus import EventBus
    from horus.processes.processTable import ProcessTable

_AMBIENT_TEMPERATURE_CELSIUS = 25.0  # room temperature -- the system can't cool below this on its own
_THERMAL_SCALE = 0.05  # tunable: how many degC a net watt of heat vs. cooling shifts the system by per tick


def _default_motherboard() -> Motherboard:
    """The stock "Horus X1" board -- same numbers the old flat
    HardwareSpec fields used to default to (cpu_mhz=3200, cpu_cores=1,
    memory_kb='65536K', memory_count=2, coolant_type='Water',
    coolant_amount=99)."""
    return Motherboard(
        name="Horus X1",
        manufacturer="Horus Inc.",
        power_usage_watts=20,
        cpu_sockets=[
            CpuSocket(name="Socket A", supported_cpus=[
                Cpu(name="Coeles X3201", cores=1, mhz=3200,
                    power_usage_watts_max=65, power_usage_watts_min=5,
                    manufacturer="Coeles"),
            ]),
        ],
        ram_slots=[
            RamSlots(name="DIMM A", supported_ram_types=[
                Ram(name="Horus DDR", size=16384, manufacturer="Horus Inc.",
                    power_usage_watts_min=1, power_usage_watts_max=10),
            ]),
            RamSlots(name="DIMM B", supported_ram_types=[
                Ram(name="Horus DDR", size=16384, manufacturer="Horus Inc.",
                    power_usage_watts_min=1, power_usage_watts_max=10),
            ]),
        ],
        storage_slots=[
            StorageSlots(name="SATA A", supported_storage_types=[
                Storage(name="Horus HDD", size=524288, manufacturer="Horus Inc.",
                         power_usage_watts=3),
            ]),
        ],
        network_interfaces=[
            NetworkInterface(name="eth0", mac_address="00:00:00:00:00:01",
                              ip_address="10.0.0.2", manufacturer="Horus Inc.",
                              power_usage_watts=2),
        ],
        cooling_system=CoolingSystem(
            name="Coolant System",
            manufacturer="Horus Inc.",
            power_usage_watts_max=50,
            coolant_type=CoolantType.WATER,
            coolant_amount=99,
            temperature_celsius=25.0,
        ),
    )


def _default_power_supply_unit() -> PowerSupplyUnit:
    return PowerSupplyUnit(name="Horus PSU", manufacturer="Horus Inc.", power_output_watts=500)


@dataclass
class HardwareSpec:
    """The simulated machine's hardware configuration. Every component
    (CPU, RAM, Storage, Network, Cooling) lives under `motherboard` as real
    Cpu/Ram/Storage/NetworkInterface/CoolingSystem instances -- HardwareSpec
    itself is a thin façade over that tree (see the cpu_name/cpu_mhz/...
    properties below for the flat, backward-compatible view of it)."""

    motherboard: Motherboard = field(default_factory=_default_motherboard)
    power_supply_unit: PowerSupplyUnit = field(default_factory=_default_power_supply_unit)
    temperature_celsius: float = _AMBIENT_TEMPERATURE_CELSIUS  # current simulated system temperature

    def __post_init__(self) -> None:
        # Deliberately not dataclass fields: this is runtime telemetry for a
        # future line graph in the Power/Cooling detail panels, not
        # configuration -- it must stay out of to_dict()/save()/load() and
        # out of the dataclass-generated __eq__ (two HardwareSpecs with
        # identical hardware but different sample history are still "equal"
        # hardware, e.g. after a save/load round trip).
        self.power_history = MetricHistory()
        self.cooling_history = MetricHistory()

    def _installed_cpus(self) -> list[Cpu]:
        return [cpu for socket in self.motherboard.cpu_sockets for cpu in socket.supported_cpus]

    def _installed_ram(self) -> list[Ram]:
        return [ram for slot in self.motherboard.ram_slots for ram in slot.supported_ram_types]

    def _installed_storage(self) -> list[Storage]:
        return [s for slot in self.motherboard.storage_slots for s in slot.supported_storage_types]

    # --- flat, backward-compatible view of the first installed component ---

    @property
    def cpu_name(self) -> str:
        cpus = self._installed_cpus()
        return cpus[0].name if cpus else ""

    @property
    def cpu_mhz(self) -> int:
        cpus = self._installed_cpus()
        return cpus[0].mhz if cpus else 0

    @property
    def cpu_cores(self) -> int:
        cpus = self._installed_cpus()
        return cpus[0].cores if cpus else 0

    @property
    def memory_kb(self) -> str:
        """Per-module size, formatted like the old flat field (e.g. '65536K')
        -- matches how the boot sequence displays it ('{memory_count} x
        {memory_size}')."""
        ram = self._installed_ram()
        return f"{ram[0].size}K" if ram else "0K"

    @property
    def memory_count(self) -> int:
        return len(self._installed_ram())

    @property
    def coolant_type(self) -> str:
        return self.motherboard.cooling_system.coolant_type.value

    @property
    def coolant_amount(self) -> int:
        return self.motherboard.cooling_system.coolant_amount

    # --- capacity/usage ---

    def total_memory_kb(self) -> int:
        """Total simulated RAM in KB across every installed stick."""
        return sum(ram.size for ram in self._installed_ram())

    def total_cpu_mhz(self) -> int:
        """Total simulated CPU capacity in MHz across every installed CPU."""
        return sum(cpu.mhz * cpu.cores for cpu in self._installed_cpus())

    def calculate_total_power_usage(self) -> float:
        """Current combined draw across every component. CPU/RAM scale with
        their live `load` (see start_power_monitoring), Cooling scales with
        how much coolant is left (see CoolingSystem.calc_current_power_usage);
        everything else draws a fixed amount since nothing drives it yet."""
        total = 0.0
        total += sum(cpu.calc_current_power_usage() for cpu in self._installed_cpus())
        total += sum(ram.calc_current_power_usage() for ram in self._installed_ram())
        total += sum(storage.power_usage_watts for storage in self._installed_storage())
        total += sum(iface.power_usage_watts for iface in self.motherboard.network_interfaces)
        total += self.motherboard.cooling_system.calc_current_power_usage()
        total += self.motherboard.power_usage_watts
        return total

    # --- periodic PSU budget check ---

    def start_power_monitoring(self, process_table: "ProcessTable", events: "EventBus",
                                interval: float = 2.0) -> None:
        """Periodically syncs installed CPUs'/RAM's `load` from the live
        ProcessTable, then publishes a PowerUsageCheckedEvent reporting the
        combined draw against the PSU's output -- every tick, not just on
        crossing the threshold, so subscribers always see current state.
        Call once; safe to call again after stop_power_monitoring()."""
        self._process_table = process_table
        self._events = events
        pyglet.clock.schedule_interval(self._check_power_usage, interval)

    def stop_power_monitoring(self) -> None:
        pyglet.clock.unschedule(self._check_power_usage)

    def _sync_component_load_from_process_table(self) -> None:
        table = self._process_table
        cpu_load = table.used_cpu_mhz() / table.total_cpu_mhz if table.total_cpu_mhz else 0.0
        mem_load = table.used_mem_kb() / table.total_memory_kb if table.total_memory_kb else 0.0
        for cpu in self._installed_cpus():
            cpu.load = cpu_load
        for ram in self._installed_ram():
            ram.load = mem_load

    def _check_power_usage(self, dt: float) -> None:
        self._sync_component_load_from_process_table()
        self._update_temperature()
        total_power_usage = self.calculate_total_power_usage()
        psu_output_watts = self.power_supply_unit.power_output_watts
        self.power_history.record(total_power_usage)
        self.cooling_history.record(self.motherboard.cooling_system.calc_current_power_usage())
        self._events.publish(PowerUsageCheckedEvent(
            total_power_usage=total_power_usage,
            psu_output_watts=psu_output_watts,
            over_budget=total_power_usage > psu_output_watts,
        ))

    # --- temperature ---

    def _update_temperature(self) -> None:
        """System temperature drifts based on the balance between heat
        generated by loaded CPU/RAM (their current electrical draw --
        virtually all of it becomes heat) and what the cooling system can
        carry away (CoolingSystem.calculate_cooling_power): net-positive
        heat raises the temperature, net-positive cooling lowers it, floored
        at ambient since nothing here can actively refrigerate below room
        temperature. Also keeps the cooling system's own reading
        (CoolingSystem.temperature_celsius) in sync, so it reflects the same
        system-wide value rather than a second, disconnected number."""
        heat_generated = sum(cpu.calc_current_power_usage() for cpu in self._installed_cpus())
        heat_generated += sum(ram.calc_current_power_usage() for ram in self._installed_ram())
        cooling_power = self.motherboard.cooling_system.calculate_cooling_power()
        self.temperature_celsius = max(
            _AMBIENT_TEMPERATURE_CELSIUS,
            self.temperature_celsius + (heat_generated - cooling_power) * _THERMAL_SCALE,
        )
        self.motherboard.cooling_system.update_temperature(self.temperature_celsius)

    # --- persistence ---

    def to_dict(self) -> dict:
        return {
            "motherboard": self.motherboard.to_dict(),
            "power_supply_unit": self.power_supply_unit.to_dict(),
            "temperature_celsius": self.temperature_celsius,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HardwareSpec":
        return cls(
            motherboard=Motherboard.from_dict(data["motherboard"]),
            power_supply_unit=PowerSupplyUnit.from_dict(data["power_supply_unit"]),
            temperature_celsius=data.get("temperature_celsius", _AMBIENT_TEMPERATURE_CELSIUS),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "HardwareSpec":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
