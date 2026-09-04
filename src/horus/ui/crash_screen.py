import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen

_DEFAULT_DELAY = 4.0  # seconds before the window actually closes


class CrashScreen(Screen):
    """Takes over the terminal after a critical process (e.g. init, PID 1)
    is killed: freezes all input, shows a kernel-panic-style message, and
    closes the window after `delay` seconds. There's no recovering from
    this -- it's the end of the session, matching a real OS going down hard
    when its init process dies."""

    def __init__(self, buffer: ScreenBuffer, window, proc_name: str, delay: float = _DEFAULT_DELAY) -> None:
        self._buffer = buffer
        self._window = window  # anything with .close(); None is safe (just never closes)
        self._proc_name = proc_name
        self._delay = delay

    def on_push(self) -> None:
        self._buffer.cursor_enabled = False
        self._buffer.clear()
        self._render()
        pyglet.clock.schedule_once(self._close_window, self._delay)

    def _render(self) -> None:
        lines = [
            "*** KERNEL PANIC ***",
            "",
            f"Fatal exception: essential process '{self._proc_name}' terminated unexpectedly.",
            "",
            "System halted.",
        ]
        top = max(0, (self._buffer.rows - len(lines)) // 2)
        for i, line in enumerate(lines):
            col = max(0, (self._buffer.cols - len(line)) // 2)
            self._buffer.write_string(col, top + i, line)

    def _close_window(self, dt: float) -> None:
        if self._window is not None:
            self._window.close()

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        pass

    def handle_enter(self) -> None:
        pass

    def handle_key(self, symbol: int, modifiers: int) -> None:
        pass
