from unittest.mock import patch

from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.events.types import ProcessKilledEvent, ProcessStartedEvent
from horus.processes.system_reactions import register_system_reactions
from horus.ui.crash_screen import CrashScreen
from horus.ui.screen_manager import ScreenManager


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
