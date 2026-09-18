from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.box_drawing import draw_box
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key


class DetailScreen(Screen):
    """Generic full-panel detail view: one bordered box spanning the whole
    buffer, with a title and a list of lines. Escape pops back. Used both
    for a single hardware component (opened by pressing Enter on one of
    HardwareScreen's tiles, see HardwareTile.on_select) and for the 'err'
    command's warning/error log.

    `refresh`, if given, is called (with no arguments) every `refresh_interval`
    seconds and must return a fresh list of lines to display -- the same
    live-refresh idiom HardwareScreen itself uses (see TopScreen), so live
    values (load, draw, temperature, new log entries, ...) don't go stale
    while this screen stays open. Leaving `refresh` unset keeps the lines
    static."""

    def __init__(self, buffer: ScreenBuffer, title: str, lines: list[str], screens: ScreenManager,
                 refresh: Callable[[], list[str]] | None = None, refresh_interval: float = 1.0) -> None:
        self._buffer = buffer
        self._title = title
        self._lines = lines
        self._screens = screens
        self._refresh = refresh
        self._refresh_interval = refresh_interval
        self._saved_screen: dict | None = None

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._buffer.clear()
        self._render()
        if self._refresh is not None:
            pyglet.clock.schedule_interval(self._tick, self._refresh_interval)

    def on_pop(self) -> None:
        """restore() also brings back cursor_enabled from the snapshot, so this
        correctly leaves the cursor disabled when popping back into another menu
        instead of always re-enabling it as if the shell was always underneath."""
        if self._refresh is not None:
            pyglet.clock.unschedule(self._tick)
        self._buffer.restore(self._saved_screen)

    def _tick(self, dt: float) -> None:
        self._lines = self._refresh()
        self._render()

    def _render(self) -> None:
        # clear() also resets _writes -- see SettingScreen._render() for why
        # that matters once a resize (e.g. font size change) can happen while
        # this screen is showing.
        self._buffer.clear()
        draw_box(self._buffer, 0, 0, self._buffer.cols, self._buffer.rows, self._title, self._lines)

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        pass

    def handle_enter(self) -> None:
        pass

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
