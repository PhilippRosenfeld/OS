from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pyglet

from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager
from horus.display.screen_buffer import ScreenBuffer


@dataclass
class BootFrame:
    text: str
    delay: float = 0.55   # seconds before the next frame/line appears

class BootScreen(Screen):
    def __init__(self, buffer: ScreenBuffer, frames: list[BootFrame],
                 on_complete: Callable[[], None]) -> None:
        self._buffer = buffer
        self._frames = frames
        self._on_complete = on_complete
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

    def on_pop(self) -> None:
        pyglet.clock.unschedule(self._advance)
        self._buffer.clear()

    def on_resume(self) -> None:
        pass  # boot screen never sits underneath another screen

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
        self._row += 1
        self._index += 1

        if self._index < len(self._frames):
            self._schedule_next(self._frames[self._index].delay)
        else:
            self._schedule_next(0.5)  # brief pause after the last line

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        pyglet.clock.unschedule(self._advance)
        self._on_complete()

    # --- Screen interface: any input skips the animation ---
    def handle_text(self, text: str) -> None:
        self._finish()

    def handle_motion(self, motion: int) -> None:
        self._finish()

    def handle_enter(self) -> None:
        self._finish()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        self._finish()