from horus.shell.input_handler import InputHandler
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager


class ShellScreen(Screen):
    """Adapts InputHandler to the Screen interface, so the normal shell is just
    the bottom-most screen on the ScreenManager's stack."""

    def __init__(self, input_handler: InputHandler, screens: ScreenManager, window=None) -> None:
        self._input_handler = input_handler
        self._screens = screens
        self._window = window  # anything with .start_cursor_blink(); None skips the guard below
        self._cursor_blink_started = False

    def on_push(self) -> None:
        """Deliberately does NOT start the cursor blink -- at app start this
        fires before Boot/Logo/Main Menu get pushed on top, and starting the
        blink here would flip cursor_visible underneath those screens too
        (they only set it False once in their own on_push())."""
        self._input_handler.start_line()

    def on_resume(self) -> None:
        """Called when a submenu above us closes -- redraw the prompt for the line
        that was waiting underneath it, and start the cursor blink the first
        time the shell is actually revealed (see on_push() for why not there)."""
        self._input_handler.start_line()
        if self._window is not None and not self._cursor_blink_started:
            self._window.start_cursor_blink()
            self._cursor_blink_started = True


    def handle_text(self, text: str) -> None:
        self._input_handler._handle_text(text)

    def handle_motion(self, motion: int) -> None:
        self._input_handler._handle_motion(motion)

    def handle_enter(self) -> None:
        self._input_handler._handle_enter()
        if self._screens.active is self:  # the submitted command may have opened a
            self._input_handler.start_line()  # different screen -- don't draw over it

    def handle_key(self, symbol: int, modifiers: int) -> None:
        self._input_handler._handle_key(symbol, modifiers)
