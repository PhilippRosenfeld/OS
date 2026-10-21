from typing import Callable

import pyglet

from horus.shell.input_handler import InputHandler
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key


class ShellScreen(Screen):
    """Adapts InputHandler to the Screen interface, so the normal shell is just
    the bottom-most screen on the ScreenManager's stack."""

    def __init__(self, input_handler: InputHandler, screens: ScreenManager, window=None,
                 on_escape: Callable[[], None] | None = None) -> None:
        self._input_handler = input_handler
        self._screens = screens
        self._window = window  # anything with .start_cursor_blink(); None skips the guard below
        self._on_escape = on_escape  # opens the settings menu; None (e.g. minimal test setups) skips it
        self._cursor_blink_started = False
        self._needs_prompt = False  # a command opened another screen before the next prompt was drawn

    def on_push(self) -> None:
        """Deliberately does NOT start the cursor blink -- at app start this
        fires before Boot/Logo/Main Menu get pushed on top, and starting the
        blink here would flip cursor_visible underneath those screens too
        (they only set it False once in their own on_push())."""
        self._input_handler.start_line()
        self._needs_prompt = False

    def on_resume(self) -> None:
        """Called when a submenu above us closes, or when a WindowManager on
        top of us hands us the focus -- draw the prompt a command left
        pending (see handle_enter), and start the cursor blink the first
        time the shell is actually revealed (see on_push() for why not there)."""
        if self._needs_prompt:
            self._input_handler.start_line()
            self._needs_prompt = False
        if self._window is not None and not self._cursor_blink_started:
            self._window.start_cursor_blink()
            self._cursor_blink_started = True


    def handle_text(self, text: str) -> None:
        self._input_handler._handle_text(text)

    def handle_motion(self, motion: int) -> None:
        self._input_handler._handle_motion(motion)

    def handle_enter(self) -> None:
        """The submitted command may have opened a different screen -- then
        don't draw the next prompt over it, leave it for on_resume(). Compared
        against whatever was on top before (not against `self`), since input
        can also reach us forwarded through a WindowManager on top."""
        top = self._screens.active
        self._input_handler._handle_enter()
        if self._screens.active is top:
            self._input_handler.start_line()
        else:
            self._needs_prompt = True

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE and self._on_escape is not None:
            self._on_escape()
            return
        self._input_handler._handle_key(symbol, modifiers)
