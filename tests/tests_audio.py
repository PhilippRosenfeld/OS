from unittest.mock import patch

import pyglet
import pytest

from horus.audio.sound_manager import SoundManager
from horus.paths import BOOT_SOUNDS_DIR


def test_load_missing_file_does_not_raise():
    sm = SoundManager()
    sm.load("nope", "does/not/exist.wav")  # should not raise


def test_play_unloaded_name_is_a_noop():
    sm = SoundManager()
    sm.play("never_loaded")  # should not raise


def test_load_and_play_real_file_does_not_raise():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.play("tick")  # should not raise, regardless of whether a real audio device exists


def test_play_swallows_driver_errors():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    with patch.object(sm._sources["tick"], "play", side_effect=RuntimeError("no audio device")):
        sm.play("tick")  # should not raise even if the driver fails


def test_play_prunes_finished_players():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.play("tick")
    sm.play("tick")
    assert len(sm._players) <= 2  # sanity: doesn't accumulate unboundedly on repeated calls


# --- volume ---

def test_default_volume_is_full():
    sm = SoundManager()
    assert sm.volume == 1.0


def test_set_volume_clamps_to_valid_range():
    sm = SoundManager()
    sm.set_volume(1.5)
    assert sm.volume == 1.0
    sm.set_volume(-0.5)
    assert sm.volume == 0.0


def test_play_applies_current_volume_to_new_players():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.set_volume(0.3)
    sm.play("tick")
    assert sm._players[-1].volume == pytest.approx(0.3)


def test_set_volume_updates_currently_playing_sounds():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.play("tick")
    sm.set_volume(0.2)
    assert sm._players[-1].volume == pytest.approx(0.2)


# --- per-sound volume ---

def test_set_sound_volume_applies_on_play():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.set_sound_volume("tick", 0.5)
    sm.play("tick")
    assert sm._players[-1].volume == pytest.approx(0.5)


def test_set_sound_volume_combines_with_master_volume():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.set_volume(0.5)
    sm.set_sound_volume("tick", 0.4)
    sm.play("tick")
    assert sm._players[-1].volume == pytest.approx(0.2)  # 0.5 * 0.4


def test_sounds_without_a_set_sound_volume_default_to_full_relative_volume():
    sm = SoundManager()
    sm.load("a", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.set_volume(0.6)
    sm.play("a")
    assert sm._players[-1].volume == pytest.approx(0.6)


def test_set_sound_volume_updates_that_currently_playing_sound():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.play("tick")
    sm.set_sound_volume("tick", 0.3)
    assert sm._players[-1].volume == pytest.approx(0.3)


def test_set_sound_volume_does_not_affect_other_currently_playing_sounds():
    sm = SoundManager()
    sm.load("a", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.load("b", BOOT_SOUNDS_DIR / "boot_complete.wav")
    sm.play("a")
    sm.play("b")
    player_a, player_b = sm._players[-2], sm._players[-1]
    sm.set_sound_volume("a", 0.1)
    assert player_a.volume == pytest.approx(0.1)
    assert player_b.volume == pytest.approx(1.0)  # untouched


def test_set_sound_volume_clamps_to_valid_range():
    sm = SoundManager()
    sm.set_sound_volume("tick", 5.0)
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.play("tick")
    assert sm._players[-1].volume == pytest.approx(1.0)


def test_play_sequence_applies_per_sound_volume_as_queue_advances():
    sm = SoundManager()
    sm.load("a", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.load("b", BOOT_SOUNDS_DIR / "boot_complete.wav")
    sm.set_sound_volume("a", 0.8)
    sm.set_sound_volume("b", 0.2)
    sm.play_sequence(["a", "b"])
    player = sm._players[-1]
    assert player.volume == pytest.approx(0.8)  # starts on "a"

    player.dispatch_event("on_player_next_source")  # simulate advancing to "b"
    assert player.volume == pytest.approx(0.2)


# --- play_sequence ---

def test_play_sequence_does_not_raise_with_real_files():
    sm = SoundManager()
    sm.load("a", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.load("b", BOOT_SOUNDS_DIR / "boot_complete.wav")
    sm.play_sequence(["a", "b"])  # should not raise
    assert len(sm._players) == 1  # one Player queuing both sources, not two separate ones


def test_play_sequence_skips_unknown_names():
    sm = SoundManager()
    sm.load("a", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.play_sequence(["a", "does_not_exist"])  # should not raise
    assert len(sm._players) == 1


def test_play_sequence_with_no_known_names_is_a_noop():
    sm = SoundManager()
    sm.play_sequence(["nope", "also_nope"])  # should not raise
    assert sm._players == []


def test_play_sequence_applies_current_volume():
    sm = SoundManager()
    sm.load("a", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.set_volume(0.4)
    sm.play_sequence(["a"])
    assert sm._players[-1].volume == pytest.approx(0.4)


# --- fade_in ---

def test_fade_in_unloaded_name_returns_none_and_schedules_nothing():
    sm = SoundManager()
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        player = sm.fade_in("never_loaded", target_volume=1.0, duration=1.0)
    assert player is None
    mock_schedule.assert_not_called()


def test_fade_in_starts_silent_and_returns_the_player():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    with patch("pyglet.clock.schedule_interval"):
        player = sm.fade_in("tick", target_volume=1.0, duration=1.0)
    assert player is not None
    assert player.volume == pytest.approx(0.0)
    assert player in sm._players


def test_fade_in_interpolates_volume_up_to_target_over_steps():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    captured = {}
    with patch("pyglet.clock.schedule_interval", side_effect=lambda func, interval: captured.update(func=func)):
        player = sm.fade_in("tick", target_volume=0.8, duration=1.0, step=0.25)

    tick = captured["func"]
    tick(0.25)
    assert player.volume == pytest.approx(0.2)
    tick(0.25)
    assert player.volume == pytest.approx(0.4)
    tick(0.25)
    assert player.volume == pytest.approx(0.6)
    tick(0.25)
    assert player.volume == pytest.approx(0.8)


def test_fade_in_defaults_target_volume_to_effective_volume():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.set_volume(0.5)
    sm.set_sound_volume("tick", 0.4)
    captured = {}
    with patch("pyglet.clock.schedule_interval", side_effect=lambda func, interval: captured.update(func=func)):
        player = sm.fade_in("tick", duration=1.0, step=1.0)  # target_volume omitted

    captured["func"](1.0)  # single step -> fully at target
    assert player.volume == pytest.approx(0.2)  # 0.5 * 0.4


def test_fade_in_sets_loop_flag():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    with patch("pyglet.clock.schedule_interval"):
        looping = sm.fade_in("tick", target_volume=1.0, duration=1.0, loop=True)
        not_looping = sm.fade_in("tick", target_volume=1.0, duration=1.0, loop=False)
    assert looping.loop is True
    assert not_looping.loop is False


def test_fade_in_clamps_target_volume():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    captured = {}
    with patch("pyglet.clock.schedule_interval", side_effect=lambda func, interval: captured.update(func=func)):
        player = sm.fade_in("tick", target_volume=5.0, duration=0.1, step=0.1)
    captured["func"](0.1)
    assert player.volume == pytest.approx(1.0)


# --- fade_out ---

def test_fade_out_with_nothing_playing_does_not_schedule_anything():
    sm = SoundManager()
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        sm.fade_out(0.0, duration=1.0)
    mock_schedule.assert_not_called()


def test_fade_out_interpolates_volume_over_steps():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.set_volume(1.0)
    sm.play("tick")
    player = sm._players[-1]

    captured = {}
    with patch("pyglet.clock.schedule_interval", side_effect=lambda func, interval: captured.update(func=func, interval=interval)):
        sm.fade_out(target_volume=0.0, duration=1.0, step=0.25)

    assert captured["interval"] == 0.25
    tick = captured["func"]

    tick(0.25)
    assert player.volume == pytest.approx(0.75)
    tick(0.25)
    assert player.volume == pytest.approx(0.5)
    tick(0.25)
    assert player.volume == pytest.approx(0.25)
    tick(0.25)  # final step -> exactly at target
    assert player.volume == pytest.approx(0.0)


def test_fade_out_towards_a_nonzero_target_level():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.set_volume(1.0)
    sm.play("tick")
    player = sm._players[-1]

    captured = {}
    with patch("pyglet.clock.schedule_interval", side_effect=lambda func, interval: captured.update(func=func)):
        sm.fade_out(target_volume=0.4, duration=1.0, step=0.5)  # 2 steps

    tick = captured["func"]
    tick(0.5)
    assert player.volume == pytest.approx(0.7)  # halfway from 1.0 to 0.4
    tick(0.5)
    assert player.volume == pytest.approx(0.4)


def test_fade_out_unschedules_itself_once_target_is_reached():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.play("tick")

    captured = {}
    with patch("pyglet.clock.schedule_interval", side_effect=lambda func, interval: captured.update(func=func)):
        with patch("pyglet.clock.unschedule") as mock_unschedule:
            sm.fade_out(target_volume=0.5, duration=0.1, step=0.1)  # exactly 1 step
            mock_unschedule.assert_not_called()
            captured["func"](0.1)
            mock_unschedule.assert_called_once()


def test_fade_out_clamps_target_volume():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    sm.play("tick")
    player = sm._players[-1]

    captured = {}
    with patch("pyglet.clock.schedule_interval", side_effect=lambda func, interval: captured.update(func=func)):
        sm.fade_out(target_volume=5.0, duration=0.1, step=0.1)

    captured["func"](0.1)
    assert player.volume == pytest.approx(1.0)  # clamped to the valid max, not 5.0


# --- play_delayed ---

def test_play_delayed_schedules_via_pyglet_clock():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    with patch("pyglet.clock.schedule_once") as mock_schedule:
        sm.play_delayed("tick", 5.0)
    mock_schedule.assert_called_once()
    (func, delay), _kwargs = mock_schedule.call_args
    assert delay == 5.0
    assert sm._players == []  # hasn't played yet -- only scheduled


def test_play_delayed_plays_once_the_delay_elapses():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    captured = {}
    with patch("pyglet.clock.schedule_once", side_effect=lambda func, delay: captured.update(func=func)):
        sm.play_delayed("tick", 5.0)

    assert sm._players == []
    captured["func"](5.0)  # simulate the delay having elapsed
    assert len(sm._players) == 1


def test_play_delayed_returns_a_cancellable_handle():
    sm = SoundManager()
    sm.load("tick", BOOT_SOUNDS_DIR / "boot_tick.wav")
    handle = sm.play_delayed("tick", 5.0)
    pyglet.clock.unschedule(handle)  # should not raise
    pyglet.clock.tick()  # even if the clock advances, nothing should fire now
    assert sm._players == []


def test_play_delayed_with_unloaded_name_does_not_raise_once_fired():
    sm = SoundManager()
    captured = {}
    with patch("pyglet.clock.schedule_once", side_effect=lambda func, delay: captured.update(func=func)):
        sm.play_delayed("never_loaded", 1.0)
    captured["func"](1.0)  # should not raise -- play() is a no-op for unknown names
