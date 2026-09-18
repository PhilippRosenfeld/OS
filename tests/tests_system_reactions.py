from unittest.mock import patch

from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.events.system_log import LogSeverity, SystemLog
from horus.events.types import PowerUsageCheckedEvent, ProcessKilledEvent, ProcessStartedEvent
from horus.processes.system_reactions import register_system_log, register_system_reactions
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
