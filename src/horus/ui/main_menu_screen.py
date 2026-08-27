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

    def __init__(self, buffer: ScreenBuffer, title: str, options: list[MenuOption], sounds=None,
                 song: str | None = None, song_volume: float = 0.05, song_fade_in: float = 2.0,
                 song_fade_out: float = 6.0) -> None:
        self._buffer = buffer
        self._title = title
        self._options = options
        self._selected = 0
        self._saved_screen: dict | None = None
        self._sounds = sounds  # anything with .fade_in(name, ...)/.fade_out(...); None disables the theme
        self._song = song
        self._song_volume = song_volume
        self._song_fade_in = song_fade_in
        self._song_fade_out = song_fade_out
        self._song_player = None

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._buffer.clear()
        self._selected = 0
        self._render()
        if self._sounds is not None and self._song is not None and self._song_player is None:
            self._song_player = self._sounds.fade_in(
                self._song, target_volume=self._song_volume, duration=self._song_fade_in, loop=True)

    def on_pop(self) -> None:
        """Fades the theme out (e.g. picking "Continue" and returning to the
        shell) rather than cutting it off -- but note this only fires when
        THIS screen is popped, not when a submenu like Settings is pushed on
        top of it, so the theme keeps looping uninterrupted while browsing
        Settings (see on_resume)."""
        self._buffer.restore(self._saved_screen)
        if self._sounds is not None and self._song_player is not None:
            player = self._song_player
            self._sounds.fade_out(0.0, duration=self._song_fade_out, on_complete=player.pause)
        self._song_player = None

    def on_resume(self) -> None:
        self._render()
        # theme keeps looping uninterrupted while a submenu (e.g. Settings) was open

    def _render(self) -> None:
        # clear() also resets _writes -- see SettingScreen._render() for why
        # that matters once a resize (e.g. font size change) can happen while
        # this screen is showing.
        self._buffer.clear()
        row = max(1, (self._buffer.rows - len(self._options)) // 2 - 3)
        col = max(0, (self._buffer.cols - len(self._title)) // 2)
        self._buffer.write_string(col, row, self._title)

        start_row = row + 3
        widest_option = max((len(option.label) for option in self._options), default=0) + 2  # +2 for "> "/"  " prefix
        option_col = max(0, (self._buffer.cols - widest_option) // 2)
        for i, option in enumerate(self._options):
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