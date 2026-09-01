from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager


class LoadingScreen(Screen):
    """Owns the keyboard while a command's fake-async effect (e.g. encrypt/
    decrypt's progress bar) is running, so the shell underneath doesn't print
    a fresh prompt or blink its cursor over the animation -- the command
    dispatch that pushed this screen has already returned by the time the
    animation is still ticking via pyglet.clock, so without this the shell
    would think the command finished and start accepting input right away.

    All input is swallowed rather than acted on. Popping this (once the
    animation completes) hands control back to whatever is underneath,
    which redraws its own prompt/cursor via its on_resume()."""

    def __init__(self, buffer: ScreenBuffer, screens: ScreenManager) -> None:
        self._buffer = buffer
        self._screens = screens
        self._saved_cursor_enabled = True

    def on_push(self) -> None:
        self._saved_cursor_enabled = self._buffer.cursor_enabled
        self._buffer.cursor_enabled = False

    def on_pop(self) -> None:
        self._buffer.cursor_enabled = self._saved_cursor_enabled

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        pass

    def handle_enter(self) -> None:
        pass

    def handle_key(self, symbol: int, modifiers: int) -> None:
        pass
