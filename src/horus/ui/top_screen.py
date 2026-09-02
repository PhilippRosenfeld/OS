import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.processes.processTable import ProcessTable
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key


class TopScreen(Screen):
    """Live process view, unlike ps's one-shot listing: redraws the process
    table every `refresh_interval` seconds via pyglet.clock, reflecting
    whatever the ProcessTable currently holds, until dismissed with Ctrl+C."""

    def __init__(self, buffer: ScreenBuffer, process_table: ProcessTable, screens: ScreenManager,
                 refresh_interval: float = 1.0) -> None:
        self._buffer = buffer
        self._process_table = process_table
        self._screens = screens
        self._refresh_interval = refresh_interval
        self._saved_screen: dict | None = None

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._render()
        pyglet.clock.schedule_interval(self._tick, self._refresh_interval)

    def on_pop(self) -> None:
        pyglet.clock.unschedule(self._tick)
        self._buffer.restore(self._saved_screen)

    def _tick(self, dt: float) -> None:
        self._render()

    def _render(self) -> None:
        self._buffer.clear()
        self._buffer.write_string(0, 0, f"{'PID':<8}{'USER':<12}{'CPU%':<8}{'MEM(KB)':<12}{'NAME'}")
        self._buffer.write_string(0, 1, "-" * 60)

        last_row = self._buffer.rows - 1
        for i, proc in enumerate(self._process_table.list_processes()):
            row = i + 2
            if row >= last_row:
                break
            self._buffer.write_string(0, row, f"{proc.pid:<8}{proc.owner:<12}{proc.cpu_percent:<8.2f}{proc.mem_kb:<12}{proc.name}")

        self._buffer.write_string(0, last_row, "Ctrl+C to exit")

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        pass

    def handle_enter(self) -> None:
        pass

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.C and modifiers & key.MOD_CTRL:
            self._screens.pop()
