from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key


class MenuOption:
    """A single selectable entry: what it's called, and what happens on Enter."""

    def __init__(self, label: str, on_select: Callable[[], None]) -> None:
        self.label = label
        self.on_select = on_select


class MenuScreen(Screen):
    """A minimal vertical list menu: Up/Down moves the selection, Enter activates
    it, Escape goes back to whatever screen was active before. Proof of concept
    for the Screen stack -- later menus (settings, save/load, start screen) can
    reuse this shape."""

    def __init__(self, buffer: ScreenBuffer, title: str, options: list[MenuOption], screens: ScreenManager) -> None:
        self._buffer = buffer
        self._title = title
        self._options = options
        self._screens = screens
        self._selected = 0
        self._saved_screen: dict | None = None

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._buffer.clear()
        self._render()

    def on_pop(self) -> None:
        """restore() also brings back cursor_enabled from the snapshot, so this
        correctly leaves the cursor disabled when popping back into another menu
        instead of always re-enabling it as if the shell was always underneath."""
        self._buffer.restore(self._saved_screen)

    def _render(self) -> None:
        self._buffer.write_string(0, 0, self._title)
        for i, option in enumerate(self._options):
            row = i + 2
            if i == self._selected:
                self._buffer.write_string(0, row, f"> {option.label}", fg=self._buffer.default_bg, bg=self._buffer.default_fg)
            else:
                self._buffer.write_string(0, row, f"  {option.label}")

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        if motion == key.MOTION_UP:
            self._selected = (self._selected - 1) % len(self._options)
            self._render()
        elif motion == key.MOTION_DOWN:
            self._selected = (self._selected + 1) % len(self._options)
            self._render()

    def handle_enter(self) -> None:
        self._options[self._selected].on_select()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
