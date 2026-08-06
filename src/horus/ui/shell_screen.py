from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager
from horus.shell.input_handler import InputHandler


class ShellScreen(Screen):
    """Adapts InputHandler to the Screen interface, so the normal shell is just
    the bottom-most screen on the ScreenManager's stack."""

    def __init__(self, input_handler: InputHandler, screens: ScreenManager) -> None:
        self._input_handler = input_handler
        self._screens = screens

    def on_push(self) -> None:
        self._input_handler.start_line()

    def on_resume(self) -> None:
        """Called when a submenu above us closes -- redraw the prompt for the line
        that was waiting underneath it."""
        self._input_handler.start_line()

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
