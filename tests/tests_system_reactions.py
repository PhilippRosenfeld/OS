from unittest.mock import patch

from horus.display.screen_buffer import ScreenBuffer
from horus.display.status_bar import StatusBar
from horus.events.bus import EventBus
from horus.events.system_log import LogSeverity, SystemLog
from horus.events.types import PowerUsageCheckedEvent, ProcessKilledEvent, ProcessStartedEvent, TemperatureCriticalEvent, TemperatureWarningEvent
from horus.processes.process import process as Process
from horus.processes.system_reactions import (
    register_status_bar,
    register_system_log,
    register_system_reactions,
    register_temperature_reactions,
)
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.crash_screen import CrashScreen


class FakeSounds:
    def __init__(self) -> None:
        self.played: list[str] = []
        self.volumes: dict[str, float] = {}

    def play(self, name: str) -> None:
        self.played.append(name)

    def set_sound_volume(self, name: str, volume: float) -> None:
        self.volumes[name] = volume


def test_critical_kill_pushes_a_crash_screen():
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    register_system_reactions(bus, screens, window=None, sounds=None, buffer=buffer)

    with patch("pyglet.clock.schedule_once"):
        bus.publish(ProcessKilledEvent(pid=1, name="init", killed_by="root", critical=True))

    assert isinstance(screens.active, CrashScreen)


def test_critical_kill_plays_the_crash_sounds():
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    sounds = FakeSounds()
    register_system_reactions(bus, screens, window=None, sounds=sounds, buffer=buffer)

    with patch("pyglet.clock.schedule_once"):
        bus.publish(ProcessKilledEvent(pid=1, name="init", killed_by="root", critical=True))

    assert sounds.played == ["system_crashed", "process_kill_buzz"]
    assert sounds.volumes["system_crashed"] == 0.5


def test_non_critical_kill_does_not_push_a_crash_screen():
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    register_system_reactions(bus, screens, window=None, sounds=None, buffer=buffer)

    bus.publish(ProcessKilledEvent(pid=2, name="bash", killed_by="user1", critical=False))

    assert screens.active is None


def test_non_critical_kill_does_not_play_any_sound():
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    sounds = FakeSounds()
    register_system_reactions(bus, screens, window=None, sounds=sounds, buffer=buffer)

    bus.publish(ProcessKilledEvent(pid=2, name="bash", killed_by="user1", critical=False))

    assert sounds.played == []


def test_critical_kill_without_screens_does_not_raise():
    bus = EventBus()
    buffer = ScreenBuffer(60, 10)
    register_system_reactions(bus, screens=None, window=None, sounds=None, buffer=buffer)

    bus.publish(ProcessKilledEvent(pid=1, name="init", killed_by="root", critical=True))  # should not raise


def test_critical_kill_without_sounds_still_pushes_the_crash_screen():
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    register_system_reactions(bus, screens, window=None, sounds=None, buffer=buffer)

    with patch("pyglet.clock.schedule_once"):
        bus.publish(ProcessKilledEvent(pid=1, name="init", killed_by="root", critical=True))

    assert isinstance(screens.active, CrashScreen)


def test_process_started_event_does_not_trigger_a_reaction():
    """register_system_reactions only subscribes to ProcessKilledEvent --
    publishing an unrelated event type must not do anything."""
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    register_system_reactions(bus, screens, window=None, sounds=None, buffer=buffer)

    bus.publish(ProcessStartedEvent(pid=1, name="init", owner="root"))  # should not raise or push anything

    assert screens.active is None


def test_crash_screen_receives_the_killed_process_name():
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    register_system_reactions(bus, screens, window=None, sounds=None, buffer=buffer)

    with patch("pyglet.clock.schedule_once"):
        bus.publish(ProcessKilledEvent(pid=1, name="init", killed_by="root", critical=True))

    screen_text = "".join(
        "".join(buffer.get_cell(c, r).char for c in range(buffer.cols)) for r in range(buffer.rows)
    )
    assert "init" in screen_text


# --- register_temperature_reactions ---

def test_temperature_warning_does_not_push_a_crash_screen():
    """Regression guard: a mere warning-level temperature must not trigger
    the kernel-panic-and-close-the-window treatment -- only
    TemperatureCriticalEvent does. Firing this every tick the system stays
    hot previously spammed a new CrashScreen (and rescheduled the window
    close) on nothing worse than a warning."""
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    register_temperature_reactions(bus, screens, window=None, sounds=None, buffer=buffer)

    bus.publish(TemperatureWarningEvent(temperature=85.0, critical_temperature=90.0))

    assert screens.active is None


def test_temperature_warning_plays_a_sound():
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    sounds = FakeSounds()
    register_temperature_reactions(bus, screens, window=None, sounds=sounds, buffer=buffer)

    bus.publish(TemperatureWarningEvent(temperature=85.0, critical_temperature=90.0))

    assert sounds.played == ["system_error_notification"]


def test_temperature_critical_pushes_a_crash_screen():
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    register_temperature_reactions(bus, screens, window=None, sounds=None, buffer=buffer)
    killed = Process(name="hog", pid=3)

    with patch("pyglet.clock.schedule_once"):
        bus.publish(TemperatureCriticalEvent(temperature=95.0, critical_temperature=90.0, process_killed=killed))

    assert isinstance(screens.active, CrashScreen)


def test_temperature_critical_crash_screen_names_the_killed_process():
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(60, 10)
    register_temperature_reactions(bus, screens, window=None, sounds=None, buffer=buffer)
    killed = Process(name="hog", pid=3)

    with patch("pyglet.clock.schedule_once"):
        bus.publish(TemperatureCriticalEvent(temperature=95.0, critical_temperature=90.0, process_killed=killed))

    screen_text = "".join(
        "".join(buffer.get_cell(c, r).char for c in range(buffer.cols)) for r in range(buffer.rows)
    )
    assert "hog" in screen_text


def test_temperature_critical_crash_screen_mentions_the_critical_temperature():
    """The CrashScreen must actually say it was the critical temperature
    that killed the process, not just name the process like an ordinary
    process-killed crash."""
    bus = EventBus()
    screens = ScreenManager()
    buffer = ScreenBuffer(100, 10)  # wide enough that the message doesn't wrap across rows
    register_temperature_reactions(bus, screens, window=None, sounds=None, buffer=buffer)
    killed = Process(name="hog", pid=3)

    with patch("pyglet.clock.schedule_once"):
        bus.publish(TemperatureCriticalEvent(temperature=95.0, critical_temperature=90.0, process_killed=killed))

    screen_text = "".join(
        "".join(buffer.get_cell(c, r).char for c in range(buffer.cols)) for r in range(buffer.rows)
    )
    assert "critical temperature" in screen_text
    assert "95.0" in screen_text


# --- register_system_log ---

def test_power_overload_logs_a_warning():
    bus = EventBus()
    log = SystemLog()
    register_system_log(bus, log)

    bus.publish(PowerUsageCheckedEvent(total_power_usage=150.0, psu_output_watts=100.0, over_budget=True))

    assert len(log) == 1
    entry = log.entries()[0]
    assert entry.severity is LogSeverity.WARNING
    assert "150" in entry.message
    assert "100" in entry.message


def test_power_under_budget_does_not_log_anything():
    bus = EventBus()
    log = SystemLog()
    register_system_log(bus, log)

    bus.publish(PowerUsageCheckedEvent(total_power_usage=80.0, psu_output_watts=100.0, over_budget=False))

    assert len(log) == 0


def test_power_overload_only_logs_once_while_continuously_over_budget():
    """Regression guard: PowerUsageCheckedEvent fires every tick, not just on
    crossing the threshold -- must log the edge (False -> True), not every
    tick spent over budget."""
    bus = EventBus()
    log = SystemLog()
    register_system_log(bus, log)

    for _ in range(5):
        bus.publish(PowerUsageCheckedEvent(total_power_usage=150.0, psu_output_watts=100.0, over_budget=True))

    assert len(log) == 1


def test_power_overload_logs_again_after_recovering_and_re_exceeding():
    bus = EventBus()
    log = SystemLog()
    register_system_log(bus, log)

    bus.publish(PowerUsageCheckedEvent(total_power_usage=150.0, psu_output_watts=100.0, over_budget=True))
    bus.publish(PowerUsageCheckedEvent(total_power_usage=90.0, psu_output_watts=100.0, over_budget=False))
    bus.publish(PowerUsageCheckedEvent(total_power_usage=150.0, psu_output_watts=100.0, over_budget=True))

    assert len(log) == 2


def test_critical_process_kill_logs_an_error():
    bus = EventBus()
    log = SystemLog()
    register_system_log(bus, log)

    bus.publish(ProcessKilledEvent(pid=1, name="init", killed_by="root", critical=True))

    assert len(log) == 1
    entry = log.entries()[0]
    assert entry.severity is LogSeverity.ERROR
    assert "init" in entry.message


def test_non_critical_process_kill_does_not_log_anything():
    bus = EventBus()
    log = SystemLog()
    register_system_log(bus, log)

    bus.publish(ProcessKilledEvent(pid=2, name="bash", killed_by="user1", critical=False))

    assert len(log) == 0


def test_system_log_is_independent_of_the_sound_screen_reactions():
    """register_system_log() works even if register_system_reactions()/
    register_power_reactions() were never wired up -- it's its own
    independent subscriber, not a side effect of those."""
    bus = EventBus()
    log = SystemLog()
    register_system_log(bus, log)

    bus.publish(ProcessKilledEvent(pid=1, name="init", killed_by="root", critical=True))  # no crash-screen reaction registered

    assert len(log) == 1


# --- register_status_bar ---

def test_power_overload_lights_the_pwr_indicator():
    bus = EventBus()
    status_bar = StatusBar(40)
    register_status_bar(bus, status_bar)

    bus.publish(PowerUsageCheckedEvent(total_power_usage=150.0, psu_output_watts=100.0, over_budget=True))

    assert status_bar.is_lit("PWR") is True


def test_power_recovering_clears_the_pwr_indicator():
    """Unlike the SystemLog reaction (which only wants the edge), the status
    bar just mirrors the event's current over_budget flag every time -- it's
    always showing live state, not a history of transitions."""
    bus = EventBus()
    status_bar = StatusBar(40)
    register_status_bar(bus, status_bar)

    bus.publish(PowerUsageCheckedEvent(total_power_usage=150.0, psu_output_watts=100.0, over_budget=True))
    assert status_bar.is_lit("PWR") is True

    bus.publish(PowerUsageCheckedEvent(total_power_usage=80.0, psu_output_watts=100.0, over_budget=False))
    assert status_bar.is_lit("PWR") is False


def test_critical_process_kill_lights_the_sys_indicator():
    bus = EventBus()
    status_bar = StatusBar(40)
    register_status_bar(bus, status_bar)

    bus.publish(ProcessKilledEvent(pid=1, name="init", killed_by="root", critical=True))

    assert status_bar.is_lit("SYS") is True


def test_non_critical_process_kill_does_not_light_the_sys_indicator():
    bus = EventBus()
    status_bar = StatusBar(40)
    register_status_bar(bus, status_bar)

    bus.publish(ProcessKilledEvent(pid=2, name="bash", killed_by="user1", critical=False))

    assert status_bar.is_lit("SYS") is False


def test_msc_never_lights_up_yet():
    """No real trigger exists for MSC yet -- see register_status_bar's
    docstring. Locks in that a power overload and a critical kill only light
    their own indicator, not every light."""
    bus = EventBus()
    status_bar = StatusBar(40)
    register_status_bar(bus, status_bar)

    bus.publish(PowerUsageCheckedEvent(total_power_usage=150.0, psu_output_watts=100.0, over_budget=True))
    bus.publish(ProcessKilledEvent(pid=1, name="init", killed_by="root", critical=True))

    assert status_bar.is_lit("MSC") is False


def test_temperature_warning_lights_the_temp_indicator():
    bus = EventBus()
    status_bar = StatusBar(40)
    register_status_bar(bus, status_bar)

    bus.publish(TemperatureWarningEvent(temperature=85.0, critical_temperature=90.0))

    assert status_bar.is_lit("TEMP") is True


def test_temperature_warning_does_not_light_other_indicators():
    bus = EventBus()
    status_bar = StatusBar(40)
    register_status_bar(bus, status_bar)

    bus.publish(TemperatureWarningEvent(temperature=85.0, critical_temperature=90.0))

    assert status_bar.is_lit("PWR") is False
    assert status_bar.is_lit("SYS") is False
    assert status_bar.is_lit("MSC") is False
