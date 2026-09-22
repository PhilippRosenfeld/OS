import json
from datetime import datetime
from unittest.mock import patch

from horus.events.bus import EventBus
from horus.events.types import PowerUsageCheckedEvent, TemperatureCriticalEvent, TemperatureWarningEvent
from horus.hardware.cooling_system import CoolantType, CoolingSystem
from horus.hardware.cpu import Cpu
from horus.hardware.metric_history import MetricHistory
from horus.hardware.motherboard import CpuSocket, Motherboard, RamSlots, StorageSlots
from horus.hardware.network_interface import NetworkInterface
from horus.hardware.power_supply_unit import PowerSupplyUnit
from horus.hardware.ram import Ram
from horus.hardware.spec import HardwareSpec
from horus.hardware.storage import Storage
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable


def make_cpu(mhz=1000, cores=1, power_min=5, power_max=50):
    return Cpu(name="Test CPU", cores=cores, mhz=mhz, power_usage_watts_max=power_max,
               power_usage_watts_min=power_min, manufacturer="Test Inc.")


def make_ram(size=1024, power_min=1, power_max=4):
    return Ram(name="Test RAM", size=size, manufacturer="Test Inc.",
               power_usage_watts_min=power_min, power_usage_watts_max=power_max)


def make_motherboard(cpus=None, rams=None, storages=None, ifaces=None,
                      power_usage_watts=10, cooling_power_usage_watts=5):
    return Motherboard(
        name="Test Board", manufacturer="Test Inc.", power_usage_watts=power_usage_watts,
        cpu_sockets=[CpuSocket("Socket", cpus if cpus is not None else [make_cpu()])],
        ram_slots=[RamSlots("Slot", rams if rams is not None else [make_ram()])],
        storage_slots=[StorageSlots("Slot", storages if storages is not None else
                                     [Storage("Test Disk", 1024, "Test Inc.", power_usage_watts=3)])],
        network_interfaces=ifaces if ifaces is not None else
        [NetworkInterface("eth0", "00:11:22:33:44:55", "10.0.0.2", "Test Inc.", power_usage_watts=2)],
        cooling_system=CoolingSystem("Test Cooler", "Test Inc.", cooling_power_usage_watts),
    )


def make_spec(**motherboard_kwargs):
    return HardwareSpec(motherboard=make_motherboard(**motherboard_kwargs),
                         power_supply_unit=PowerSupplyUnit("Test PSU", "Test Inc.", power_output_watts=100))


# --- Cpu.calc_current_power_usage ---

def test_cpu_power_usage_at_zero_load_is_the_minimum():
    cpu = make_cpu(power_min=10, power_max=60)
    assert cpu.calc_current_power_usage() == 10


def test_cpu_power_usage_at_full_load_is_the_maximum():
    cpu = make_cpu(power_min=10, power_max=60)
    cpu.load = 1.0
    assert cpu.calc_current_power_usage() == 60


def test_cpu_power_usage_scales_linearly_with_load():
    cpu = make_cpu(power_min=10, power_max=60)
    cpu.load = 0.5
    assert cpu.calc_current_power_usage() == 35


def test_cpu_power_usage_clamps_load_above_one():
    cpu = make_cpu(power_min=10, power_max=60)
    cpu.load = 1.5
    assert cpu.calc_current_power_usage() == 60


def test_cpu_power_usage_clamps_load_below_zero():
    cpu = make_cpu(power_min=10, power_max=60)
    cpu.load = -0.5
    assert cpu.calc_current_power_usage() == 10


# --- Ram.calc_current_power_usage ---

def test_ram_power_usage_at_zero_load_is_the_minimum():
    ram = make_ram(power_min=2, power_max=10)
    assert ram.calc_current_power_usage() == 2


def test_ram_power_usage_at_full_load_is_the_maximum():
    ram = make_ram(power_min=2, power_max=10)
    ram.load = 1.0
    assert ram.calc_current_power_usage() == 10


def test_ram_power_usage_scales_linearly_with_load():
    ram = make_ram(power_min=2, power_max=10)
    ram.load = 0.5
    assert ram.calc_current_power_usage() == 6


def test_ram_power_usage_clamps_load_outside_zero_to_one():
    ram = make_ram(power_min=2, power_max=10)
    ram.load = 2.0
    assert ram.calc_current_power_usage() == 10
    ram.load = -2.0
    assert ram.calc_current_power_usage() == 2


# --- CoolingSystem ---

def test_cooling_system_with_no_coolant_left_cools_nothing():
    cooling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                             coolant_type=CoolantType.LIQUID_NITROGEN, coolant_amount=0,
                             base_cooling_modifier=2.0)
    assert cooling.calculate_cooling_power() == 0.0
    assert cooling.calc_current_power_usage() == 0.0


def test_cooling_system_draw_increases_with_coolant_amount():
    """More coolant -> more cooling power -> more watts drawn, monotonically.
    Pinned at the max temperature_celsius so the new temperature throttle
    (see _temperature_factor) runs at 1.0 and doesn't interfere -- this test
    is only about the coolant_amount axis."""
    draws = [
        CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                       coolant_type=CoolantType.WATER, coolant_amount=amount,
                       temperature_celsius=90.0).calc_current_power_usage()
        for amount in (0, 25, 50, 75, 100)
    ]
    assert draws == sorted(draws)
    assert draws[0] == 0.0
    assert draws[-1] == 50


def test_cooling_system_stronger_coolant_type_draws_more_power():
    """A more effective coolant produces more cooling power for the same
    amount/modifier -- and, per calc_current_power_usage, that costs more
    energy to run, not less (until it hits the unit's rated max). Pinned at
    the max temperature_celsius, see test_cooling_system_draw_increases_
    with_coolant_amount above."""
    def draw_for(coolant_type):
        return CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                              coolant_type=coolant_type, coolant_amount=50,
                              temperature_celsius=90.0).calc_current_power_usage()

    assert draw_for(CoolantType.AIR) < draw_for(CoolantType.WATER) < draw_for(CoolantType.OIL)


def test_cooling_system_draw_is_capped_at_power_usage_watts_max():
    """A coolant type/modifier combo strong enough to exceed the unit's
    rated wattage still can't draw more than power_usage_watts_max. Pinned
    at the max temperature_celsius, see test_cooling_system_draw_increases_
    with_coolant_amount above."""
    cooling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                             coolant_type=CoolantType.LIQUID_NITROGEN, coolant_amount=100,
                             base_cooling_modifier=2.0, temperature_celsius=90.0)
    assert cooling.calculate_cooling_power() > 50  # would exceed the rating uncapped
    assert cooling.calc_current_power_usage() == 50


def test_cooling_system_cooling_power_drops_in_a_hotter_environment():
    """A hotter room leaves less of a gradient to dump heat into, so the
    same unit delivers less cooling power than at neutral (25C). Pinned at
    the max temperature_celsius, see test_cooling_system_draw_increases_
    with_coolant_amount above."""
    def power_at(env_temp):
        return CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50, coolant_amount=100,
                              env_temperature_celsius=env_temp, temperature_celsius=90.0).calculate_cooling_power()

    assert power_at(45.0) < power_at(25.0) < power_at(5.0)


def test_cooling_system_idles_when_no_hotter_than_the_environment():
    """The new bit: the unit shouldn't run at its rated power all the time --
    at/below the environment's own temperature there's nothing to cool, so
    it should produce (and draw) no cooling power at all."""
    cooling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                             coolant_amount=100, temperature_celsius=25.0, env_temperature_celsius=25.0)
    assert cooling.calculate_cooling_power() == 0.0
    assert cooling.calc_current_power_usage() == 0.0


def test_cooling_system_ramps_up_with_temperature():
    """Between idling at the environment's temperature and running flat out
    at _MAX_COOLING_TEMPERATURE_CELSIUS, cooling power increases smoothly
    with how hot the system currently is."""
    def power_at(temp):
        return CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                              coolant_amount=100, temperature_celsius=temp).calculate_cooling_power()

    assert power_at(25.0) < power_at(50.0) < power_at(90.0)


def test_cooling_system_temperature_factor_caps_at_one_above_the_max():
    """Running even hotter than _MAX_COOLING_TEMPERATURE_CELSIUS can't push
    the unit past its already-flat-out 1.0 temperature factor."""
    cooling_at_max = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                                    coolant_amount=100, temperature_celsius=90.0)
    cooling_past_max = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                                      coolant_amount=100, temperature_celsius=150.0)
    assert cooling_at_max.calculate_cooling_power() == cooling_past_max.calculate_cooling_power()


def test_cooling_system_update_temperature_recomputes_cached_cooling_power():
    cooling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50, coolant_amount=100)
    cooling.update_temperature(80.0)
    assert cooling.temperature_celsius == 80.0
    assert cooling._cooling_power == cooling.calculate_cooling_power()


def test_cooling_system_save_then_load_round_trips():
    cooling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                             coolant_type=CoolantType.LIQUID_NITROGEN, coolant_amount=42,
                             temperature_celsius=30.0, base_cooling_modifier=1.3)
    loaded = CoolingSystem.from_dict(cooling.to_dict())
    assert loaded == cooling
    assert loaded.coolant_type is CoolantType.LIQUID_NITROGEN


def test_cooling_system_deactivated_cools_nothing_regardless_of_everything_else():
    """A deactivated unit produces (and draws) zero cooling power no matter
    how strong its coolant/type/rating would otherwise make it."""
    cooling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                             coolant_type=CoolantType.LIQUID_NITROGEN, coolant_amount=100,
                             temperature_celsius=90.0, base_cooling_modifier=2.0, active=False)
    assert cooling.calculate_cooling_power() == 0.0
    assert cooling.calc_current_power_usage() == 0.0


def test_cooling_system_defaults_to_active():
    cooling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50)
    assert cooling.active is True


def test_cooling_system_max_cooling_temperature_is_configurable_per_instance():
    """Regression guard: this used to be a module-level constant shared by
    every CoolingSystem -- now it's a per-instance field so one unit's
    tuning can't leak into another's."""
    low_ceiling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50, coolant_amount=100,
                                 temperature_celsius=50.0, max_cooling_temperature_celsius=50.0)
    high_ceiling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50, coolant_amount=100,
                                  temperature_celsius=50.0, max_cooling_temperature_celsius=200.0)
    # low_ceiling is already at its max -- running flat out; high_ceiling still has a long way to go
    assert low_ceiling.calculate_cooling_power() > high_ceiling.calculate_cooling_power()


def test_cooling_system_active_and_max_cooling_temperature_persist_through_save_and_load():
    cooling = CoolingSystem("Cooler", "Test Inc.", power_usage_watts_max=50,
                             active=False, max_cooling_temperature_celsius=123.0)
    loaded = CoolingSystem.from_dict(cooling.to_dict())
    assert loaded == cooling
    assert loaded.active is False
    assert loaded.max_cooling_temperature_celsius == 123.0


# --- HardwareSpec: defaults / flat backward-compatible properties ---

def test_defaults_when_nothing_loaded():
    spec = HardwareSpec()
    assert spec.cpu_cores == 1
    assert spec.memory_count == 2


def test_default_flat_properties_delegate_to_the_installed_components():
    spec = HardwareSpec()
    assert spec.cpu_name == "Coele X551"
    assert spec.cpu_mhz == 550
    assert spec.memory_kb == "16384K"
    assert spec.coolant_type == "Water"
    assert spec.coolant_amount == 99


def test_two_hardware_specs_default_to_independent_motherboards():
    """Regression guard: motherboard/power_supply_unit used to be bare
    instance defaults shared across every HardwareSpec(), a classic mutable-
    default-argument hazard -- mutating one must not affect the other."""
    a, b = HardwareSpec(), HardwareSpec()
    a.motherboard.cpu_sockets[0].supported_cpus[0].mhz = 9999
    assert b.cpu_mhz == 550


# --- save / load ---

def test_save_then_load_round_trips_all_fields(tmp_path):
    path = tmp_path / "hardware.json"
    spec = make_spec(cpus=[make_cpu(mhz=4800, cores=8)])
    spec.save(path)

    loaded = HardwareSpec.load(path)
    assert loaded == spec


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "hardware.json"
    HardwareSpec().save(path)
    assert path.exists()


def test_load_missing_file_returns_defaults(tmp_path):
    spec = HardwareSpec.load(tmp_path / "does_not_exist.json")
    assert spec == HardwareSpec()


# --- total_memory_kb / total_cpu_mhz (used to size ProcessTable's budget) ---

def test_total_memory_kb_sums_every_installed_stick():
    spec = make_spec(rams=[make_ram(size=16384), make_ram(size=16384)])
    assert spec.total_memory_kb() == 32768


def test_total_memory_kb_with_default_spec():
    spec = HardwareSpec()  # two 16384K sticks
    assert spec.total_memory_kb() == 32768


def test_total_cpu_mhz_multiplies_mhz_by_cores():
    spec = make_spec(cpus=[make_cpu(mhz=4800, cores=8)])
    assert spec.total_cpu_mhz() == 38400


def test_total_cpu_mhz_sums_every_installed_cpu():
    spec = make_spec(cpus=[make_cpu(mhz=1000, cores=1), make_cpu(mhz=2000, cores=2)])
    assert spec.total_cpu_mhz() == 1000 + 4000


def test_total_cpu_mhz_with_default_spec():
    spec = HardwareSpec()  # cpu_mhz=550, cpu_cores=1
    assert spec.total_cpu_mhz() == 550


# --- calculate_total_power_usage ---

def test_calculate_total_power_usage_combines_every_component_at_idle():
    spec = make_spec(
        cpus=[make_cpu(power_min=5, power_max=50)],
        rams=[make_ram(power_min=1, power_max=4)],
        storages=[Storage("Disk", 1024, "Test Inc.", power_usage_watts=3)],
        ifaces=[NetworkInterface("eth0", "00:00", "0.0.0.0", "Test Inc.", power_usage_watts=2)],
        power_usage_watts=10, cooling_power_usage_watts=5,
    )
    spec.motherboard.cooling_system.temperature_celsius = 90.0  # pin the cooling throttle at 1.0 --
                                                                  # this test is about combining components,
                                                                  # not about CoolingSystem's own temperature curve
    # idle: cpu 5 + ram 1 + storage 3 + network 2 + cooling 5 + board 10
    assert spec.calculate_total_power_usage() == 26


def test_calculate_total_power_usage_scales_cpu_and_ram_with_load():
    spec = make_spec(
        cpus=[make_cpu(power_min=5, power_max=50)],
        rams=[make_ram(power_min=1, power_max=4)],
        storages=[Storage("Disk", 1024, "Test Inc.", power_usage_watts=3)],
        ifaces=[NetworkInterface("eth0", "00:00", "0.0.0.0", "Test Inc.", power_usage_watts=2)],
        power_usage_watts=10, cooling_power_usage_watts=5,
    )
    spec.motherboard.cooling_system.temperature_celsius = 90.0  # see test above
    spec.motherboard.cpu_sockets[0].supported_cpus[0].load = 1.0
    spec.motherboard.ram_slots[0].supported_ram_types[0].load = 1.0
    # full load: cpu 50 + ram 4 + storage 3 + network 2 + cooling 5 + board 10
    assert spec.calculate_total_power_usage() == 74


# --- power monitoring ---

def test_start_power_monitoring_schedules_via_pyglet_clock():
    spec = HardwareSpec()
    table = ProcessTable()
    events = EventBus()
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        spec.start_power_monitoring(table, events, interval=3.0)
    mock_schedule.assert_called_once()
    callback, interval = mock_schedule.call_args[0]
    assert interval == 3.0
    assert callback == spec._check_power_usage


def test_stop_power_monitoring_unschedules_the_tick():
    spec = HardwareSpec()
    with patch("pyglet.clock.unschedule") as mock_unschedule:
        spec.stop_power_monitoring()
    mock_unschedule.assert_called_once_with(spec._check_power_usage)


def test_check_power_usage_publishes_an_event_under_budget():
    spec = make_spec(cpus=[make_cpu(power_min=5, power_max=50)])
    table = ProcessTable(total_cpu_mhz=1000, total_memory_kb=1024)
    events = EventBus()
    received = []
    events.subscribe(PowerUsageCheckedEvent, received.append)

    spec.start_power_monitoring(table, events)
    spec._check_power_usage(dt=0.0)

    assert len(received) == 1
    evt = received[0]
    assert evt.psu_output_watts == 100
    assert evt.over_budget is False


def test_check_power_usage_publishes_an_event_over_budget():
    spec = make_spec(cpus=[make_cpu(power_min=5, power_max=500)])
    table = ProcessTable(total_cpu_mhz=1000, total_memory_kb=1024)
    table.add_process(Process(name="hog", pid=0, owner="root", cpu_mhz=1000, mem_kb=1))
    events = EventBus()
    received = []
    events.subscribe(PowerUsageCheckedEvent, received.append)

    spec.start_power_monitoring(table, events)
    spec._check_power_usage(dt=0.0)

    evt = received[0]
    assert evt.total_power_usage > evt.psu_output_watts
    assert evt.over_budget is True


def test_check_power_usage_syncs_cpu_and_ram_load_from_the_process_table():
    spec = make_spec()
    table = ProcessTable(total_cpu_mhz=1000, total_memory_kb=1000)
    table.add_process(Process(name="hog", pid=0, owner="root", cpu_mhz=900, mem_kb=500))
    events = EventBus()

    spec.start_power_monitoring(table, events)
    spec._check_power_usage(dt=0.0)

    assert spec.motherboard.cpu_sockets[0].supported_cpus[0].load == 0.9
    assert spec.motherboard.ram_slots[0].supported_ram_types[0].load == 0.5


def test_check_power_usage_records_power_and_cooling_history():
    spec = make_spec()
    table = ProcessTable(total_cpu_mhz=1000, total_memory_kb=1024)
    events = EventBus()

    spec.start_power_monitoring(table, events)
    spec._check_power_usage(dt=0.0)
    spec._check_power_usage(dt=0.0)

    assert len(spec.power_history) == 2
    assert spec.power_history.latest() == spec.calculate_total_power_usage()
    assert len(spec.cooling_history) == 2
    assert spec.cooling_history.latest() == spec.motherboard.cooling_system.calc_current_power_usage()
    assert len(spec.temperature_history) == 2
    assert spec.temperature_history.latest() == spec.temperature_celsius


# --- system temperature ---

def test_hardware_spec_starts_at_ambient_temperature():
    assert HardwareSpec().temperature_celsius == 25.0


def test_update_temperature_rises_when_heat_exceeds_cooling():
    spec = make_spec(cpus=[make_cpu(power_min=5, power_max=50)], cooling_power_usage_watts=5)
    spec.motherboard.cpu_sockets[0].supported_cpus[0].load = 1.0  # draws 50W, cooling only carries 5W
    before = spec.temperature_celsius
    spec._update_temperature()
    assert spec.temperature_celsius > before


def test_update_temperature_cools_back_toward_ambient_when_idle():
    # rated cooling power high enough to still dominate idle heat even
    # throttled down at 40C (see CoolingSystem._temperature_factor)
    spec = make_spec(cooling_power_usage_watts=500)
    spec.temperature_celsius = 40.0
    spec._update_temperature()
    assert spec.temperature_celsius < 40.0


def test_update_temperature_never_drops_below_ambient():
    """Even an enormous amount of cooling relative to heat can't push the
    temperature below ambient -- max() floors it. Heat is zeroed out and the
    starting temperature is nudged just above ambient so the cooling
    throttle (idle exactly at ambient, see CoolingSystem._temperature_factor)
    actually engages."""
    spec = make_spec(
        cpus=[make_cpu(power_min=0, power_max=0)], rams=[make_ram(power_min=0, power_max=0)],
        storages=[Storage("Disk", 1024, "Test Inc.", power_usage_watts=0)],
        ifaces=[NetworkInterface("eth0", "00:00", "0.0.0.0", "Test Inc.", power_usage_watts=0)],
        power_usage_watts=0, cooling_power_usage_watts=100000,
    )
    spec.temperature_celsius = 26.0
    spec._update_temperature()
    assert spec.temperature_celsius == 25.0


def test_update_temperature_rises_when_no_coolant_left():
    """An empty cooling system can't cool anything (see
    CoolingSystem.calculate_cooling_power), so any heat at all raises the
    system's temperature regardless of how strong the unit is rated."""
    spec = make_spec(cpus=[make_cpu(power_min=5, power_max=50)], cooling_power_usage_watts=1000)
    spec.motherboard.cooling_system.coolant_amount = 0
    spec.motherboard.cpu_sockets[0].supported_cpus[0].load = 1.0
    before = spec.temperature_celsius
    spec._update_temperature()
    assert spec.temperature_celsius > before


def test_update_temperature_rises_from_idle_non_compute_components_alone():
    """Storage, network and the motherboard's own base draw generate heat
    too, even with CPU/RAM completely idle -- not just CPU/RAM as before."""
    spec = make_spec(cpus=[make_cpu(power_min=0, power_max=0)], rams=[make_ram(power_min=0, power_max=0)],
                      power_usage_watts=10, cooling_power_usage_watts=0)
    before = spec.temperature_celsius
    spec._update_temperature()
    assert spec.temperature_celsius > before


def test_update_temperature_keeps_the_cooling_system_reading_in_sync():
    spec = make_spec()
    spec._update_temperature()
    assert spec.motherboard.cooling_system.temperature_celsius == spec.temperature_celsius


def test_check_power_usage_updates_the_temperature():
    spec = make_spec(cpus=[make_cpu(power_min=5, power_max=50)])
    table = ProcessTable(total_cpu_mhz=1000, total_memory_kb=1024)
    table.add_process(Process(name="hog", pid=0, owner="root", cpu_mhz=1000, mem_kb=1))
    events = EventBus()

    spec.start_power_monitoring(table, events)
    before = spec.temperature_celsius
    spec._check_power_usage(dt=0.0)

    assert spec.temperature_celsius > before


def test_check_temperature_publishes_with_over_warning_false_below_the_threshold():
    """Regression guard: the event still fires every tick regardless of the
    threshold (see its own docstring) -- what changes is only its
    over_warning flag, e.g. so a status-bar light can auto-clear."""
    spec = make_spec()
    events = EventBus()
    spec._events = events
    received = []
    events.subscribe(TemperatureWarningEvent, received.append)

    spec.temperature_celsius = 79.9
    spec._check_temperature()

    assert len(received) == 1
    assert received[0].over_warning is False


def test_check_temperature_publishes_a_warning_above_the_threshold():
    spec = make_spec()
    events = EventBus()
    spec._events = events
    received = []
    events.subscribe(TemperatureWarningEvent, received.append)

    spec.temperature_celsius = 85.0
    spec._check_temperature()

    assert len(received) == 1
    assert received[0].temperature == 85.0
    assert received[0].critical_temperature == spec.critical_temperature


def test_check_temperature_triggers_a_shutdown_above_the_critical_threshold():
    """The whole system crashes outright above the critical threshold -- no
    process is singled out or killed (unlike a critical process kill)."""
    spec = make_spec()
    table = ProcessTable(total_cpu_mhz=1000, total_memory_kb=1024)
    table.add_process(Process(name="hog", pid=1, owner="root", cpu_mhz=100, mem_kb=1))
    events = EventBus()
    spec._events = events
    spec._process_table = table
    warnings = []
    criticals = []
    events.subscribe(TemperatureWarningEvent, warnings.append)
    events.subscribe(TemperatureCriticalEvent, criticals.append)

    spec.temperature_celsius = 95.0
    spec._check_temperature()

    assert len(warnings) == 1  # still crosses the (lower) warning threshold too
    assert len(criticals) == 1
    assert criticals[0].temperature == 95.0
    assert spec._thermal_shutdown_triggered is True
    assert table.get_process(1) is not None  # nothing was killed


def test_check_temperature_stops_reacting_once_a_shutdown_has_fired():
    """Regression guard: while the system stays critically hot, repeated
    ticks must not keep publishing more critical events -- the first
    shutdown already latches the system into "going down", so everything
    past that point is a no-op."""
    spec = make_spec()
    table = ProcessTable(total_cpu_mhz=1000, total_memory_kb=1024)
    table.add_process(Process(name="hog", pid=1, owner="root", cpu_mhz=100, mem_kb=1))
    events = EventBus()
    spec._events = events
    spec._process_table = table
    warnings = []
    criticals = []
    events.subscribe(TemperatureWarningEvent, warnings.append)
    events.subscribe(TemperatureCriticalEvent, criticals.append)

    spec.temperature_celsius = 95.0
    for _ in range(5):
        spec._check_temperature()

    assert len(warnings) == 1
    assert len(criticals) == 1
    assert len(table.processes) == 1  # nothing was ever killed


def test_handle_thermal_shutdown_does_not_depend_on_any_processes_existing():
    """Regression guard: a thermal shutdown used to require at least one
    process to kill and silently do nothing without one -- now it always
    fires, since it no longer touches the process table at all."""
    spec = make_spec()
    table = ProcessTable(total_cpu_mhz=1000, total_memory_kb=1024)  # no processes added
    events = EventBus()
    spec._events = events
    spec._process_table = table
    received = []
    events.subscribe(TemperatureCriticalEvent, received.append)

    spec.temperature_celsius = 95.0
    spec._check_temperature()

    assert len(received) == 1
    assert spec._thermal_shutdown_triggered is True


def test_check_power_usage_fires_temperature_reactions_when_hot():
    """Regression guard: _check_power_usage (the actual periodic tick) must
    call _check_temperature too, not just _update_temperature -- otherwise
    TemperatureWarningEvent/TemperatureCriticalEvent never fire in the real
    game loop even though the temperature itself is tracked correctly."""
    spec = make_spec()
    table = ProcessTable(total_cpu_mhz=1000, total_memory_kb=1024)
    events = EventBus()
    received = []
    events.subscribe(TemperatureWarningEvent, received.append)

    spec.start_power_monitoring(table, events)
    spec.temperature_celsius = 85.0
    spec._check_power_usage(dt=0.0)

    assert len(received) == 1


def test_hardware_spec_temperature_persists_through_save_and_load(tmp_path):
    spec = HardwareSpec()
    spec.temperature_celsius = 47.3
    path = tmp_path / "hardware.json"
    spec.save(path)

    loaded = HardwareSpec.load(path)
    assert loaded.temperature_celsius == 47.3
    assert loaded == spec


def test_hardware_spec_load_falls_back_to_ambient_for_old_save_files(tmp_path):
    """Regression guard: a save file written before temperature_celsius
    existed must still load instead of raising a KeyError."""
    spec = HardwareSpec()
    path = tmp_path / "hardware.json"
    spec.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["temperature_celsius"]
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = HardwareSpec.load(path)
    assert loaded.temperature_celsius == 25.0


# --- MetricHistory ---

def test_metric_history_starts_empty():
    history = MetricHistory()
    assert len(history) == 0
    assert history.values() == []
    assert history.latest() is None


def test_metric_history_records_values_in_order():
    history = MetricHistory()
    history.record(1.0)
    history.record(2.0)
    history.record(3.0)
    assert history.values() == [1.0, 2.0, 3.0]
    assert history.latest() == 3.0
    assert len(history) == 3


def test_metric_history_drops_the_oldest_sample_once_full():
    history = MetricHistory(maxlen=3)
    for value in (1.0, 2.0, 3.0, 4.0):
        history.record(value)
    assert history.values() == [2.0, 3.0, 4.0]
    assert len(history) == 3


def test_metric_history_samples_carry_a_timestamp():
    history = MetricHistory()
    history.record(5.0, timestamp=datetime(2026, 1, 1, 12, 0, 0))
    sample = history.samples()[0]
    assert sample.value == 5.0
    assert sample.timestamp == datetime(2026, 1, 1, 12, 0, 0)


def test_metric_history_defaults_the_timestamp_to_now():
    before = datetime.now()
    history = MetricHistory()
    history.record(1.0)
    after = datetime.now()
    assert before <= history.samples()[0].timestamp <= after


# --- HardwareSpec power/cooling history ---

def test_hardware_spec_starts_with_empty_history():
    spec = HardwareSpec()
    assert len(spec.power_history) == 0
    assert len(spec.cooling_history) == 0
    assert len(spec.temperature_history) == 0


def test_hardware_spec_history_is_independent_per_instance():
    """Regression guard, same spirit as
    test_two_hardware_specs_default_to_independent_motherboards -- each
    HardwareSpec must get its own MetricHistory, not a shared one."""
    a, b = HardwareSpec(), HardwareSpec()
    a.power_history.record(42.0)
    assert len(b.power_history) == 0


def test_hardware_spec_history_is_excluded_from_equality_and_persistence(tmp_path):
    """History is runtime telemetry, not config -- two otherwise-identical
    specs stay equal regardless of sample history, and it never touches the
    save file (see HardwareSpec.__post_init__)."""
    spec = HardwareSpec()
    spec.power_history.record(99.0)

    path = tmp_path / "hardware.json"
    spec.save(path)
    assert "power_history" not in path.read_text(encoding="utf-8")

    loaded = HardwareSpec.load(path)
    assert loaded == spec
    assert len(loaded.power_history) == 0  # a fresh instance, no borrowed history
