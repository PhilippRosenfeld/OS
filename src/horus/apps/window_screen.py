import copy

import pyglet

from horus.apps.window import Window
from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager


class WindowScreen(Screen):
    """Hosts a single Window as a screen: centered over whatever was on
    screen before (which stays visible around it), focused, updated every
    `refresh_interval` seconds and composited into the main buffer.
    Closing the window pops this screen and brings the previous one back.

    The stand-in for a window manager: one that runs several windows side
    by side only has to provide the same host interface (close_window,
    is_active, screens, main_buffer) -- the windows don't change."""

    def __init__(self, buffer: ScreenBuffer, screens: ScreenManager, window: Window,
                 refresh_interval: float = 0.1) -> None:
        self._buffer = buffer
        self._screens = screens
        self.window = window
        self._refresh_interval = refresh_interval
        self._saved_screen: dict | None = None
        self._position = (0, 0)
        self._layout_size: tuple[int, int] | None = None

    # --- host interface (see apps.window) ---

    @property
    def screens(self) -> ScreenManager:
        return self._screens

    @property
    def main_buffer(self) -> ScreenBuffer:
        return self._buffer

    def is_active(self, window: Window) -> bool:
        return window is self.window and self._screens.active is self

    def close_window(self, window: Window) -> None:
        if self._screens.active is self:
            self._screens.pop()  # on_pop() closes the window
        else:
            window.closed()      # something's on top of us (e.g. a CrashScreen) -- leave the stack alone

    # --- lifecycle ---

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.view_offset = 0
        width, height = self.window.preferred_size(self._buffer.cols, self._buffer.rows)
        self._place(width, height)
        self.window.open(self, width, height)
        self.window.focus()
        self._composite()
        pyglet.clock.schedule_interval(self._tick, self._refresh_interval)

    def on_pop(self) -> None:
        pyglet.clock.unschedule(self._tick)
        self.window.closed()
        self._buffer.restore(self._saved_screen)

    def on_resume(self) -> None:
        self.window.on_resume()
        self._composite()

    def _tick(self, dt: float) -> None:
        if self._screens.active is not self or not self.window.is_open:
            return
        if (self._buffer.cols, self._buffer.rows) != self._layout_size:
            self._relayout()
        self.window.update(dt)
        self._composite()

    def _place(self, width: int, height: int) -> None:
        cols, rows = self._buffer.cols, self._buffer.rows
        self._position = ((cols - width) // 2, (rows - height) // 2)
        self._layout_size = (cols, rows)

    def _relayout(self) -> None:
        """The main grid changed size -- bring the background back and
        re-fit the window to it."""
        self._buffer.restore(copy.deepcopy(self._saved_screen))  # a copy: the saved one must stay untouched
        width, height = self.window.preferred_size(self._buffer.cols, self._buffer.rows)
        self._place(width, height)
        self.window.resize(width, height)

    def _composite(self) -> None:
        """Copies the window's surface onto the main buffer at its position
        (cell by cell -- nothing piles up in the main buffer's resize
        replay log) and puts the cursor where the window wants it."""
        surface = self.window.surface
        if surface is None or not self.window.is_open:
            return
        left, top = self._position
        for row in range(surface.rows):
            if not 0 <= top + row < self._buffer.rows:
                continue
            for col in range(surface.cols):
                if 0 <= left + col < self._buffer.cols:
                    source = surface.get_cell(col, row)
                    target = self._buffer.get_cell(left + col, top + row)
                    target.char, target.fg_color, target.bg_color = source.char, source.fg_color, source.bg_color
        cursor = self.window.cursor()
        self._buffer.cursor_enabled = cursor is not None
        if cursor is not None:
            self._buffer.cursor_col, self._buffer.cursor_row = left + cursor[0], top + cursor[1]
            self._buffer.cursor_block = self.window.cursor_block
        self.window.dirty = False
        self._buffer.dirty = True

    # --- input ---

    def _after_input(self) -> None:
        if self._screens.active is self and self.window.is_open:
            self._composite()

    def handle_text(self, text: str) -> None:
        self.window.handle_text(text)
        self._after_input()

    def handle_motion(self, motion: int) -> None:
        self.window.handle_motion(motion)
        self._after_input()

    def handle_enter(self) -> None:
        self.window.handle_enter()
        self._after_input()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        self.window.handle_key(symbol, modifiers)
        self._after_input()


def show_window(ctx, window: Window) -> WindowScreen:
    """Opens `window` over the current screen -- what a command that starts
    a windowed program calls:

        @command("netman", ...)
        def netman(ctx, argv):
            show_window(ctx, NetmanWindow(ctx))
    """
    screen = WindowScreen(ctx.screen, ctx.screens, window)
    ctx.screens.push(screen)
    return screen
