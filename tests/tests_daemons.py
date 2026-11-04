"""thermald and powerd: what the hardware does without them, and how the
'sys' Cooling and Power screens show it (netd is in tests_network_screen)."""

from unittest.mock import patch

import pyglet
import pytest

from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.events.types import PowerUsageCheckedEvent
from horus.hardware.cooling_system import UNREGULATED_COOLING_FACTOR
from horus.hardware.spec import POWER_DAEMON, THERMAL_DAEMON, HardwareSpec
from horus.kernel.commands.cmd_sys import sys as sys_command
from horus.processes.processTable import ProcessTable
from horus.processes.services import find_service, start_service
from horus.session.context import Context
from horus.session.user import UserRole
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key


def screen_text(buffer):
    return "\n".join("".join(buffer.get_cell(c, r).char for c in range(buffer.cols)).rstrip()
                     for r in range(buffer.rows))


@pytest.fixture(autouse=True)
def no_clock():
    with patch("pyglet.clock.schedule_interval"), patch("pyglet.clock.unschedule"):
        yield


@pytest.fixture
def system():
    """A machine with thermald and powerd running, monitored by its
    hardware; returns (ctx, buffer, hardware, processes, events)."""
    buffer = ScreenBuffer(130, 40)
    hardware = HardwareSpec()
    events = EventBus()
    processes = ProcessTable(total_memory_kb=hardware.total_memory_kb(), total_cpu_mhz=hardware.total_cpu_mhz(),
                             events=events)
    for daemon in (THERMAL_DAEMON, POWER_DAEMON):
        start_service(find_service(daemon), processes)
    hardware.start_power_monitoring(processes, events)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, screens=ScreenManager(), events=events,
                  process_table=processes, hardware=hardware)
    return ctx, buffer, hardware, processes, events


def kill(processes, name):
    processes.remove_process(processes.get_process_by_name(name).pid, user="root", role=UserRole.ROOT)


# --- the hardware ---

def test_a_daemon_counts_as_running_until_the_hardware_is_monitored():
    assert HardwareSpec().service_running(THERMAL_DAEMON)


def test_the_hardware_sees_a_daemon_stop_and_start_again(system):
    _, _, hardware, processes, _ = system
    assert hardware.service_running(THERMAL_DAEMON)
    kill(processes, THERMAL_DAEMON)
    assert not hardware.service_running(THERMAL_DAEMON)
    start_service(find_service(THERMAL_DAEMON), processes)
    assert hardware.service_running(THERMAL_DAEMON)


def test_without_thermald_the_cooling_is_stuck_at_its_fallback_speed(system):
    _, _, hardware, processes, _ = system
    cooling = hardware.motherboard.cooling_system
    hardware.temperature_celsius = 70.0                  # hot: thermald would cool close to flat out
    hardware._update_temperature()
    regulated = cooling._temperature_factor()
    assert regulated > UNREGULATED_COOLING_FACTOR

    kill(processes, THERMAL_DAEMON)
    hardware.temperature_celsius = 70.0
    hardware._update_temperature()
    assert not cooling.regulated and cooling._temperature_factor() == UNREGULATED_COOLING_FACTOR


def test_without_powerd_nobody_reports_the_power_budget(system):
    _, _, hardware, processes, events = system
    received = []
    events.subscribe(PowerUsageCheckedEvent, received.append)
    hardware._check_power_usage(0.0)
    assert len(received) == 1
    kill(processes, POWER_DAEMON)
    hardware._check_power_usage(0.0)
    assert len(received) == 1                             # an overloaded PSU would go unnoticed
    assert len(hardware.power_history.values()) == 2      # the readings themselves go on


# --- the Cooling screen ---

def open_cooling(ctx, buffer):
    sys_command(ctx, ["-c"])
    return ctx.screens.active, screen_text(buffer)


def test_the_cooling_screen_shows_thermald(system):
    ctx, buffer, _, processes, _ = system
    _, text = open_cooling(ctx, buffer)
    assert "thermald: running" in text and "Status: OK" in text


def test_without_thermald_the_cooling_screen_says_so_and_locks_its_options(system):
    ctx, buffer, hardware, processes, _ = system
    kill(processes, THERMAL_DAEMON)
    screen, text = open_cooling(ctx, buffer)
    assert "thermald: stopped (unregulated)" in text and "Status: THERMALD STOPPED" in text
    assert screen._status.blink

    cooling = hardware.motherboard.cooling_system
    before = cooling.max_cooling_temperature_celsius
    screen.handle_motion(key.MOTION_RIGHT)               # "Maximum cooling factor at" is selected first
    assert cooling.max_cooling_temperature_celsius == before
    assert "(locked)" in screen_text(buffer)


def test_the_options_work_again_once_thermald_is_back(system):
    ctx, buffer, hardware, processes, _ = system
    kill(processes, THERMAL_DAEMON)
    screen, _ = open_cooling(ctx, buffer)
    start_service(find_service(THERMAL_DAEMON), processes)
    cooling = hardware.motherboard.cooling_system
    before = cooling.max_cooling_temperature_celsius
    screen.handle_motion(key.MOTION_RIGHT)
    assert cooling.max_cooling_temperature_celsius == before + 5.0
    assert "(locked)" not in screen_text(buffer)


def test_a_critical_temperature_outranks_a_stopped_thermald(system):
    ctx, buffer, hardware, processes, _ = system
    kill(processes, THERMAL_DAEMON)
    hardware.temperature_celsius = hardware.critical_temperature
    _, text = open_cooling(ctx, buffer)
    assert "Status: CRITICAL" in text


# --- the Power screen ---

def test_without_powerd_the_power_screen_says_so(system):
    ctx, buffer, _, processes, _ = system
    sys_command(ctx, ["-p"])
    assert "powerd: running" in screen_text(buffer)
    ctx.screens.pop()
    ctx.screens.pop()

    kill(processes, POWER_DAEMON)
    sys_command(ctx, ["-p"])
    text = screen_text(buffer)
    assert "powerd: stopped (budget unwatched)" in text and "Status: POWERD STOPPED" in text
    assert ctx.screens.active._status.blink


# --- the overview ---

def test_the_overview_tiles_show_a_stopped_daemon_on_their_first_line(system):
    ctx, buffer, hardware, processes, _ = system
    kill(processes, THERMAL_DAEMON)
    kill(processes, POWER_DAEMON)
    sys_command(ctx, [])
    text = screen_text(buffer)
    assert f"{hardware.power_supply_unit.name}, powerd stopped" in text
    assert f"{hardware.motherboard.cooling_system.name}, thermald stopped" in text
