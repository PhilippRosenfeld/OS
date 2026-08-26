from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key


class MenuOption:
    """A single main-menu entry: a label and a callback run on Enter."""

    def __init__(self, label: str, on_select: Callable[[], None]) -> None:
        self.label = label
        self.on_select = on_select


class MainMenuScreen(Screen):
    """Vertical main menu: Up/Down moves the selection, Enter activates it.
    Mirrors SettingScreen's shape, minus the value-cycling (Left/Right)."""

    def __init__(self, buffer: ScreenBuffer, title: str, options: list[MenuOption]) -> None:
        self._buffer = buffer
        self._title = title
        self._options = options
        self._selected = 0
        self._saved_screen: dict | None = None

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._buffer.clear()
        self._selected = 0
        self._render()

    def on_pop(self) -> None:
        self._buffer.restore(self._saved_screen)

    def on_resume(self) -> None:
        self._render()

    def _render(self) -> None:
        row = max(1, (self._buffer.rows - len(self._options)) // 2 - 3)
        col = max(0, (self._buffer.cols - len(self._title)) // 2)
        self._buffer.write_string(col, row, self._title)

        start_row = row + 3
        for i, option in enumerate(self._options):
            option_col = max(0, (self._buffer.cols - 20) // 2)
            if i == self._selected:
                self._buffer.write_string(option_col, start_row + i, f"> {option.label}",
                                            fg=self._buffer.default_bg, bg=self._buffer.default_fg)
            else:
                self._buffer.write_string(option_col, start_row + i, f"  {option.label}")

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
        option = self._options[self._selected]
        if option.on_select is not None:
            option.on_select()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        pass