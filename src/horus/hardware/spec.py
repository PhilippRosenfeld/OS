import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pyglet

from horus.events.types import PowerUsageCheckedEvent, TemperatureCriticalEvent, TemperatureWarningEvent
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
                Cpu(name="Coele X551", cores=1, mhz=550,
                    power_usage_watts_max=65, power_usage_watts_min=5,
                    manufacturer="Coele Systems"),
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
            power_usage_watts_max=100,
            coolant_type=CoolantType.WATER,
            coolant_amount=99,
            temperature_celsius=25.0,
            env_temperature_celsius=25.0,
            base_cooling_modifier=1.0,
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
        self.temperature_history = MetricHistory()
        self._thermal_shutdown_triggered = False  # latches once _handle_thermal_shutdown
                                                    # fires -- the system is already going
                                                    # down (see _check_temperature), so
                                                    # nothing further should act on its heat

    def installed_cpus(self) -> list[Cpu]:
        return [cpu for socket in self.motherboard.cpu_sockets for cpu in socket.supported_cpus]

    def installed_ram(self) -> list[Ram]:
        return [ram for slot in self.motherboard.ram_slots for ram in slot.supported_ram_types]

    def installed_storage(self) -> list[Storage]:
        return [s for slot in self.motherboard.storage_slots for s in slot.supported_storage_types]
    
    def installed_network_interfaces(self) -> list[NetworkInterface]:
        return [ni for slot in self.motherboard.network_slots for ni in slot.supported_network_interfaces]

    # --- flat, backward-compatible view of the first installed component ---

    @property
    def cpu_name(self) -> str:
        cpus = self.installed_cpus()
        return cpus[0].name if cpus else ""

    @property
    def cpu_mhz(self) -> int:
        cpus = self.installed_cpus()
        return cpus[0].mhz if cpus else 0

    @property
    def cpu_cores(self) -> int:
        cpus = self.installed_cpus()
        return cpus[0].cores if cpus else 0

    @property
    def memory_kb(self) -> str:
        """Per-module size, formatted like the old flat field (e.g. '65536K')
        -- matches how the boot sequence displays it ('{memory_count} x
        {memory_size}')."""
        ram = self.installed_ram()
        return f"{ram[0].size}K" if ram else "0K"

    @property
    def memory_count(self) -> int:
        return len(self.installed_ram())

    @property
    def coolant_type(self) -> str:
        return self.motherboard.cooling_system.coolant_type.value

    @property
    def coolant_amount(self) -> int:
        return self.motherboard.cooling_system.coolant_amount

    # --- capacity/usage ---

    def total_memory_kb(self) -> int:
        """Total simulated RAM in KB across every installed stick."""
        return sum(ram.size for ram in self.installed_ram())

    def total_cpu_mhz(self) -> int:
        """Total simulated CPU capacity in MHz across every installed CPU."""
        return sum(cpu.mhz * cpu.cores for cpu in self.installed_cpus())

    def calculate_total_power_usage(self) -> float:
        """Current combined draw across every component. CPU/RAM scale with
        their live `load` (see start_power_monitoring), Cooling scales with
        how much coolant is left (see CoolingSystem.calc_current_power_usage);
        everything else draws a fixed amount since nothing drives it yet."""
        total = 0.0
        total += sum(cpu.calc_current_power_usage() for cpu in self.installed_cpus())
        total += sum(ram.calc_current_power_usage() for ram in self.installed_ram())
        total += sum(storage.power_usage_watts for storage in self.installed_storage())
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
        for cpu in self.installed_cpus():
            cpu.load = cpu_load
        for ram in self.installed_ram():
            ram.load = mem_load

    def _check_power_usage(self, dt: float) -> None:
        self._sync_component_load_from_process_table()
        self._update_temperature()
        self._check_temperature()
        total_power_usage = self.calculate_total_power_usage()
        psu_output_watts = self.power_supply_unit.power_output_watts
        self.power_history.record(total_power_usage)
        self.cooling_history.record(self.motherboard.cooling_system.calc_current_power_usage())
        self.temperature_history.record(self.temperature_celsius)
        self._events.publish(PowerUsageCheckedEvent(
            total_power_usage=total_power_usage,
            psu_output_watts=psu_output_watts,
            over_budget=total_power_usage > psu_output_watts,
        ))

    # --- temperature ---
    critical_temperature: float = 90.0  # arbitrary threshold for thermal shutdown
    warning_temperature: float = 80.0  # arbitrary threshold for warning before shutdown

    def _update_temperature(self) -> None:
        """System temperature drifts based on the balance between heat
        generated by every powered component (see calculate_total_power_usage
        -- virtually all electrical draw becomes heat) and what the cooling
        system can carry away (CoolingSystem.calculate_cooling_power):
        net-positive heat raises the temperature, net-positive cooling
        lowers it, floored at ambient since nothing here can actively
        refrigerate below room temperature. The cooling system's own draw is
        excluded -- that's the power it spends *removing* heat, not adding
        it. Also keeps the cooling system's own reading
        (CoolingSystem.temperature_celsius) in sync, so it reflects the same
        system-wide value rather than a second, disconnected number -- synced
        *before* reading calculate_cooling_power() too, so the cooling
        system's temperature-based throttle (see CoolingSystem.
        _temperature_factor) always reacts to this tick's actual starting
        temperature, even if temperature_celsius was just changed directly
        (e.g. by load())."""
        self.motherboard.cooling_system.update_temperature(self.temperature_celsius)
        heat_generated = self.calculate_total_power_usage() - self.motherboard.cooling_system.calc_current_power_usage()
        cooling_power = self.motherboard.cooling_system.calculate_cooling_power()
        self.temperature_celsius = max(
            _AMBIENT_TEMPERATURE_CELSIUS,
            self.temperature_celsius + (heat_generated - cooling_power) * _THERMAL_SCALE,
        )
        self.motherboard.cooling_system.update_temperature(self.temperature_celsius)
        
    def _check_temperature(self) -> None:
        """Publishes a TemperatureWarningEvent every tick (not just while
        over the warning threshold -- see the event's own docstring), then
        triggers a thermal shutdown of the whole system if the temperature
        is over the critical threshold too. This is called from the same
        clock tick as _check_power_usage, so it runs at the same interval.

        Once a thermal shutdown has actually fired, the system is already
        going down (CrashScreen is up, the window closes itself shortly --
        see register_temperature_reactions), so this stops checking
        altogether: no more events, nothing left to react to a system
        that's already crashing."""
        if self._thermal_shutdown_triggered:
            return
        over_warning = self.temperature_celsius > self.warning_temperature
        self._events.publish(TemperatureWarningEvent(
            temperature=self.temperature_celsius,
            critical_temperature=self.critical_temperature,
            over_warning=over_warning,
        ))
        if over_warning and self.temperature_celsius > self.critical_temperature:  # critical threshold for thermal shutdown
            self._handle_thermal_shutdown()

    def _handle_thermal_shutdown(self) -> None:
        """Simulate a thermal shutdown: the whole system just goes down, the
        same way a real machine cuts power when it overheats -- no process
        is singled out or killed (unlike a critical process kill, see
        register_system_reactions). Latches _thermal_shutdown_triggered so
        _check_temperature stops calling this again on every subsequent
        tick -- one shutdown, not one per tick for as long as the system
        stays critically hot."""
        self._thermal_shutdown_triggered = True
        self._events.publish(TemperatureCriticalEvent(temperature=self.temperature_celsius, critical_temperature=self.critical_temperature))

    # --- persistence ---

    def to_dict(self) -> dict:
        return {
            "motherboard": self.motherboard.to_dict(),
            "power_supply_unit": self.power_supply_unit.to_dict(),
            "temperature_celsius": self.temperature_celsius,
            "critical_temperature": self.critical_temperature,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HardwareSpec":
        return cls(
            motherboard=Motherboard.from_dict(data["motherboard"]),
            power_supply_unit=PowerSupplyUnit.from_dict(data["power_supply_unit"]),
            temperature_celsius=data.get("temperature_celsius", _AMBIENT_TEMPERATURE_CELSIUS),
            critical_temperature=data.get("critical_temperature", 90.0),
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
