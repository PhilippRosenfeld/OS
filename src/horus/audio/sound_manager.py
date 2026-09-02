import logging
from pathlib import Path
from typing import Callable

import pyglet

logger = logging.getLogger(__name__)


class _PlayingName:
    """Tracks which loaded sound name a Player is currently playing. For a
    play() call this never changes; for a play_sequence() player it's updated
    as the queue advances, so set_volume()/set_sound_volume() can re-derive
    the correct (master * per-sound) volume for whatever is playing right now."""
    __slots__ = ("current",)

    def __init__(self, name: str) -> None:
        self.current = name


class SoundManager:
    """Loads short one-shot sound effects and plays them by name. A missing
    file or an unavailable audio driver is logged and swallowed rather than
    raised"""

    def __init__(self) -> None:
        self._sources: dict[str, pyglet.media.Source] = {}
        self._players: list[pyglet.media.Player] = []  # keep refs alive while playing
        self._player_names: dict[int, _PlayingName] = {}  # id(player) -> tracker
        self._volume: float = 1.0
        self._sound_volumes: dict[str, float] = {}  # per-sound relative volume, default 1.0

    def load(self, name: str, path: str | Path) -> None:
        try:
            self._sources[name] = pyglet.media.load(str(path), streaming=False)
        except Exception:
            logger.warning(f"failed to load sound '{name}' from {path}", exc_info=True)

    @property
    def volume(self) -> float:
        return self._volume

    def _prune(self) -> None:
        self._players = [p for p in self._players if p.playing]
        alive_ids = {id(p) for p in self._players}
        self._player_names = {pid: t for pid, t in self._player_names.items() if pid in alive_ids}

    def _effective_volume(self, name: str | None) -> float:
        if name is None:
            return self._volume
        return self._volume * self._sound_volumes.get(name, 1.0)

    def set_volume(self, volume: float) -> None:
        """Sets the master volume (0.0 = silent, 1.0 = full) that combines
        with each sound's own relative volume (see set_sound_volume). Applies
        to future play()/play_sequence() calls, and updates every sound
        currently playing."""
        self._volume = max(0.0, min(1.0, volume))
        self._prune()
        for player in self._players:
            tracker = self._player_names.get(id(player))
            try:
                player.volume = self._effective_volume(tracker.current if tracker else None)
            except Exception:
                logger.warning("failed to update volume on a playing sound", exc_info=True)

    def set_sound_volume(self, name: str, volume: float) -> None:
        """Sets a per-sound relative volume (0.0-1.0), multiplied with the
        master volume() whenever that sound plays -- e.g. so an ambient hum
        can sit quieter than a sharp click without touching the overall level.
        Also updates that sound if it's currently playing."""
        self._sound_volumes[name] = max(0.0, min(1.0, volume))
        self._prune()
        for player in self._players:
            tracker = self._player_names.get(id(player))
            if tracker is not None and tracker.current == name:
                try:
                    player.volume = self._effective_volume(name)
                except Exception:
                    logger.warning(f"failed to update volume for playing sound '{name}'", exc_info=True)

    def play(self, name: str) -> pyglet.media.Player | None:
        """Fires the sound and returns immediately. A no-op (returns None) if
        the sound wasn't loaded (or failed to load). Safe to call repeatedly
        in quick succession -- each call plays an independent, overlapping
        instance. Returns the Player in case a caller needs to stop this
        specific instance early (e.g. a screen skipped before its sound
        naturally ends) -- most callers can just ignore the return value."""
        source = self._sources.get(name)
        if source is None:
            return None
        try:
            self._prune()
            player = source.play()
            player.volume = self._effective_volume(name)
            self._players.append(player)
            self._player_names[id(player)] = _PlayingName(name)
            return player
        except Exception:
            logger.warning(f"failed to play sound '{name}'", exc_info=True)
            return None

    def play_looped(self, name: str) -> pyglet.media.Player | None:
        """Plays a loaded sound on a continuous loop until stopped, unlike
        play() which stops on its own once the clip ends. Useful for a sound
        that should last exactly as long as some process takes (e.g. a
        loading bar) rather than for a fixed clip length:

            player = sounds.play_looped("decrypt")
            ...
            player.pause()  # stop it once the process finishes

        Returns None (and does nothing) if the sound was never loaded, same
        as play(). A looped sound never ends on its own and won't be pruned
        automatically -- the caller is responsible for pausing it."""
        source = self._sources.get(name)
        if source is None:
            return None
        try:
            self._prune()
            player = pyglet.media.Player()
            player.loop = True
            player.volume = self._effective_volume(name)
            player.queue(source)
            player.play()
            self._players.append(player)
            self._player_names[id(player)] = _PlayingName(name)
            return player
        except Exception:
            logger.warning(f"failed to loop sound '{name}'", exc_info=True)
            return None

    def play_delayed(self, name: str, delay: float) -> Callable[[float], None]:
        """Plays a loaded sound after `delay` seconds -- e.g. a sound that
        should kick in partway through some other ongoing sequence, like a
        hard-disk grind starting 5 seconds after the boot screen begins:

            sounds.play_delayed("hdd_click", 5.0)

        A no-op if the sound is never loaded, same as play(). Returns the
        scheduled callback, so a caller that might get torn down before the
        delay elapses (e.g. the boot screen gets skipped) can cancel it:

            handle = sounds.play_delayed("hdd_click", 5.0)
            ...
            pyglet.clock.unschedule(handle)
        """
        def _fire(dt: float) -> None:
            self.play(name)

        pyglet.clock.schedule_once(_fire, delay)
        return _fire

    def fade_out(self, target_volume: float, duration: float = 1.5, step: float = 0.05,
                 on_complete: Callable[[], None] | None = None,
                 player: pyglet.media.Player | None = None,
                 name: str | None = None) -> None:
        """Gradually lowers the volume of every sound currently playing down to
        target_volume over `duration` seconds, then stops adjusting. Only
        touches players already active when called -- sounds started after the
        fade begins are unaffected, and the SoundManager's own volume() level
        used for future play()/play_sequence() calls is left untouched.

        Pass `player` (e.g. the Player returned by fade_in()/play()) to scope
        this to just that one instead of every currently-playing sound --
        otherwise, if something else happens to be playing at the same time
        (e.g. a separately looping background track that's still mid fade_in),
        it gets swept into this fade too and fights the other one for control
        of its own volume, leaving it stuck instead of completing.

        Pass `name` instead when the caller never held onto the Player (e.g.
        fading out an ambient sound from BootScreen once the shell is reached,
        long after BootScreen itself is gone) -- scopes this to whatever is
        currently playing under that loaded sound name:

            sounds.fade_out(0.0, duration=2.0, name="hard_disk_spinup")

        Pass on_complete to run something once the fade finishes -- e.g. to
        actually stop a looping player once it's silent, since fading it to
        0.0 alone leaves it looping forever inaudibly:

            sounds.fade_out(0.0, duration=2.0, on_complete=player.pause)
        """
        target_volume = max(0.0, min(1.0, target_volume))
        if player is not None:
            players = [player] if player.playing else []
        elif name is not None:
            self._players = [p for p in self._players if p.playing]
            players = [p for p in self._players
                       if (tracker := self._player_names.get(id(p))) is not None and tracker.current == name]
        else:
            self._players = [p for p in self._players if p.playing]
            players = list(self._players)
        starts = {id(p): p.volume for p in players}
        if not players:
            if on_complete is not None:
                on_complete()
            return

        steps = max(1, round(duration / step))
        progress_state = {"step": 0}

        def _tick(dt: float) -> None:
            progress_state["step"] += 1
            progress = min(1.0, progress_state["step"] / steps)
            for player in players:
                if not player.playing:
                    continue
                try:
                    start_volume = starts[id(player)]
                    player.volume = start_volume + (target_volume - start_volume) * progress
                except Exception:
                    logger.warning("failed to update volume while fading out", exc_info=True)
            if progress >= 1.0:
                pyglet.clock.unschedule(_tick)
                if on_complete is not None:
                    try:
                        on_complete()
                    except Exception:
                        logger.warning("fade_out on_complete callback raised", exc_info=True)

        pyglet.clock.schedule_interval(_tick, step)

    def fade_in(self, name: str, target_volume: float | None = None, duration: float = 2.0,
                loop: bool = False, step: float = 0.05) -> pyglet.media.Player | None:
        """Plays a loaded sound starting silent and ramps its volume up to
        target_volume (defaults to that sound's normal effective volume --
        master * set_sound_volume) over `duration` seconds. Pass loop=True
        for background music that should keep repeating, e.g. a menu theme:

            player = sounds.fade_in("menu_theme", target_volume=0.5, loop=True)
            ...
            player.pause()  # stop it once the menu is left

        Returns the Player (or None if the sound isn't loaded) so the caller
        can stop it later -- a looped sound never ends on its own and won't
        be pruned automatically."""
        source = self._sources.get(name)
        if source is None:
            return None
        if target_volume is None:
            target_volume = self._effective_volume(name)
        target_volume = max(0.0, min(1.0, target_volume))

        try:
            self._prune()
            player = pyglet.media.Player()
            player.loop = loop
            player.volume = 0.0
            player.queue(source)
            player.play()
            self._players.append(player)
            self._player_names[id(player)] = _PlayingName(name)
        except Exception:
            logger.warning(f"failed to fade in sound '{name}'", exc_info=True)
            return None

        steps = max(1, round(duration / step))
        progress_state = {"step": 0}

        def _tick(dt: float) -> None:
            progress_state["step"] += 1
            progress = min(1.0, progress_state["step"] / steps)
            if player.playing:
                try:
                    player.volume = target_volume * progress
                except Exception:
                    logger.warning(f"failed to update volume while fading in '{name}'", exc_info=True)
            if progress >= 1.0 or not player.playing:
                pyglet.clock.unschedule(_tick)

        pyglet.clock.schedule_interval(_tick, step)
        return player

    def play_sequence(self, names: list[str]) -> None:
        """Plays multiple loaded sounds back-to-back, in order, as a single
        queued sequence -- not overlapping, unlike separate play() calls.
        Unknown/unloaded names are skipped rather than breaking the sequence.
        Each sound's own relative volume (set_sound_volume) is applied as the
        queue advances from one to the next."""
        valid_names = [n for n in names if n in self._sources]
        sources = [self._sources[n] for n in valid_names]
        if not sources:
            return
        try:
            self._prune()
            player = pyglet.media.Player()
            tracker = _PlayingName(valid_names[0])
            state = {"index": 0}

            def _on_next_source() -> None:
                state["index"] += 1
                if state["index"] < len(valid_names):
                    tracker.current = valid_names[state["index"]]
                    try:
                        player.volume = self._effective_volume(tracker.current)
                    except Exception:
                        logger.warning("failed to update volume for next queued sound", exc_info=True)

            player.push_handlers(on_player_next_source=_on_next_source)
            player.volume = self._effective_volume(tracker.current)
            player.queue(sources)
            player.play()
            self._players.append(player)
            self._player_names[id(player)] = tracker
        except Exception:
            logger.warning(f"failed to play sound sequence {names}", exc_info=True)
