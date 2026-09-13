from dataclasses import dataclass
from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen


@dataclass
class BootFrame:
    text: str
    delay: float = 0.55   # seconds before the next frame/line appears

class BootScreen(Screen):
    def __init__(self, buffer: ScreenBuffer, frames: list[BootFrame],
                 on_complete: Callable[[], None], sounds=None,
                 fade_out_target: float = 0.01, fade_out_duration: float = 2.0) -> None:
        self._buffer = buffer
        self._frames = frames
        self._on_complete = on_complete
        self._sounds = sounds
        self._fade_out_target = fade_out_target
        self._fade_out_duration = fade_out_duration
        self._index = 0
        self._row = 0
        self._finished = False

    def on_push(self) -> None:
        self._buffer.clear()
        self._buffer.cursor_visible = False
        self._row = 0
        self._index = 0
        self._finished = False
        self._schedule_next(0.0)
        if self._sounds is not None:
            self._sounds.play("monitor_switch_on")
            self._sounds.play("hard_disk_spinup")
            self._sounds.play_delayed("startup_up_weird_noise", 5)

    def on_pop(self) -> None:
        pyglet.clock.unschedule(self._advance)
        self._buffer.clear()

    def on_resume(self) -> None:
        pass

    def _schedule_next(self, delay: float) -> None:
        pyglet.clock.schedule_once(self._advance, delay)

    def _advance(self, dt: float) -> None:
        if self._finished or self._index >= len(self._frames):
            self._finish()
            return

        frame = self._frames[self._index]

        last_row = self._buffer.rows - 1
        if self._row > last_row:
            overflow = self._row - last_row
            self._buffer.scroll(direction='u', lines=overflow)
            self._row -= overflow

        self._buffer.write_string(col=0, row=self._row, string=frame.text)
        if frame.text.strip() and self._sounds is not None:
            self._sounds.play("boot_tick")
        self._row += 1
        self._index += 1

        if self._index < len(self._frames):
            self._schedule_next(self._frames[self._index].delay)
        else:
            self._schedule_next(3.5)  # brief pause after the last line

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        pyglet.clock.unschedule(self._advance)
        if self._sounds is not None:
            # whatever ambient sounds are still going (e.g. monitor_switch_on,
            # hard_disk_spinup) fade down instead of cutting off abruptly
            self._sounds.fade_out(self._fade_out_target, self._fade_out_duration)
            self._sounds.play("boot_complete")
        self._on_complete()

    # --- Screen interface: any key press skips the animation. Only handle_key
    # and handle_enter react -- pyglet dispatches on_key_press for virtually
    # every key (including ones that also produce on_text/on_text_motion), so
    # reacting to handle_text/handle_motion too would double-fire _finish()
    # for a single physical keystroke: it would pop straight through this
    # screen AND the one pushed after it (e.g. skip Boot -> Logo -> Main Menu
    # from one keypress instead of Boot -> Logo, waiting for the next).
    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        pass

    def handle_enter(self) -> None:
        self._finish()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        self._finish()