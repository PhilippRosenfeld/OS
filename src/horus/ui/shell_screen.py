from horus.ui.screen import Screen
from horus.shell.input_handler import InputHandler


class ShellScreen(Screen):
    """Adapts InputHandler to the Screen interface, so the normal shell is just
    the bottom-most screen on the ScreenManager's stack"""

    def __init__(self, input_handler: InputHandler) -> None:
        self._input_handler = input_handler

    def handle_text(self, text: str) -> None:
        self._input_handler._handle_text(text)

    def handle_motion(self, motion: int) -> None:
        self._input_handler._handle_motion(motion)

    def handle_enter(self) -> None:
        self._input_handler._handle_enter()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        self._input_handler._handle_key(symbol, modifiers)
