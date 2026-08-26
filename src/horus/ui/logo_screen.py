from pathlib import Path
from typing import Callable

import pyglet

from horus.ui.screen import Screen
from horus.display.screen_buffer import ScreenBuffer


class LogoScreen(Screen):
    """Renders an ASCII-art logo, line by line, then holds briefly before
    handing off. Any key press skips straight to the end -- same pattern
    as BootScreen."""

    def __init__(self, buffer: ScreenBuffer, lines: list[str],
                 on_complete: Callable[[], None],
                 line_delay: float = 0.10, hold_time: float = 1.5) -> None:
        self._buffer = buffer
        self._lines = lines
        self._on_complete = on_complete
        self._line_delay = line_delay
        self._hold_time = hold_time
        self._index = 0
        self._row = 0
        self._col_offset = 0
        self._finished = False

    def on_push(self) -> None:
        self._buffer.clear()
        self._buffer.cursor_visible = False
        self._index = 0
        self._finished = False
        self._center_offset()
        self._schedule_next(0.0)

    def on_pop(self) -> None:
        pyglet.clock.unschedule(self._advance)

    def on_resume(self) -> None:
        pass

    def _center_offset(self) -> None:
        """Roughly horizontally centers the logo based on its widest line."""
        widest = max((len(l) for l in self._lines), default=0)
        self._col_offset = max(0, (self._buffer.cols - widest) // 2)
        self._row = max(0, (self._buffer.rows - len(self._lines)) // 2)

    def _schedule_next(self, delay: float) -> None:
        pyglet.clock.schedule_once(self._advance, delay)

    def _advance(self, dt: float) -> None:
        if self._finished:
            return

        if self._index >= len(self._lines):
            self._finish()
            return

        line = self._lines[self._index]
        self._buffer.write_string(col=self._col_offset, row=self._row + self._index, string=line)
        self._index += 1

        next_delay = self._line_delay if self._index < len(self._lines) else self._hold_time
        self._schedule_next(next_delay)

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        pyglet.clock.unschedule(self._advance)
        self._on_complete()

    # --- Screen interface: any input skips straight to completion ---

    def handle_text(self, text: str) -> None:
        self._finish()

    def handle_motion(self, motion: int) -> None:
        self._finish()

    def handle_enter(self) -> None:
        self._finish()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        self._finish()