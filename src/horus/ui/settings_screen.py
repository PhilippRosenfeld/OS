from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key


class SettingOption:
    """A single settings entry. If `get_value` is set, the option shows a
    current value and cycles it with Left/Right (on_left/on_right). A plain
    action entry (e.g. "Return") leaves get_value unset and only reacts to Enter
    via on_select."""

    def __init__(self, label: str, get_value: Callable[[], str] = None, on_left: Callable[[], None] = None, on_right: Callable[[], None] = None, on_select: Callable[[], None] = None) -> None:
        self.label = label
        self.get_value = get_value
        self.on_left = on_left
        self.on_right = on_right
        self.on_select = on_select


class SettingScreen(Screen):
    """Vertical settings list: Up/Down moves the selection, Left/Right cycles the
    selected setting's value, Enter activates it if it has an action, Escape goes
    back to whatever screen was active before. Mirrors MenuScreen's shape."""

    def __init__(self, buffer: ScreenBuffer, title: str, options: list[SettingOption], screens: ScreenManager) -> None:
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

    def _label_for(self, option: SettingOption) -> str:
        if option.get_value is None:
            return option.label
        return f"{option.label}: < {option.get_value()} >"

    def _render(self) -> None:
        # clear() also resets _writes -- otherwise every past render (one per
        # keypress) stays in that replay log, and a later resize (e.g. font
        # size change) re-wraps each of them at the *current* cols, which can
        # leave stale rows overlapping freshly rendered ones.
        self._buffer.clear()
        self._buffer.write_string(0, 0, self._title)
        for i, option in enumerate(self._options):
            row = i + 2
            text = self._label_for(option)
            if i == self._selected:
                self._buffer.write_string(0, row, f"> {text}", fg=self._buffer.default_bg, bg=self._buffer.default_fg)
            else:
                self._buffer.write_string(0, row, f"  {text}")

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        if motion == key.MOTION_UP:
            self._selected = (self._selected - 1) % len(self._options)
            self._render()
        elif motion == key.MOTION_DOWN:
            self._selected = (self._selected + 1) % len(self._options)
            self._render()
        elif motion == key.MOTION_LEFT:
            option = self._options[self._selected]
            if option.on_left is not None:
                option.on_left()
                self._render()
        elif motion == key.MOTION_RIGHT:
            option = self._options[self._selected]
            if option.on_right is not None:
                option.on_right()
                self._render()

    def handle_enter(self) -> None:
        option = self._options[self._selected]
        if option.on_select is not None:
            option.on_select()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
