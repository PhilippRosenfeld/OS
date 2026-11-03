from typing import Callable

import pyglet

from horus.display.screen_buffer import Inset, ScreenBuffer
from horus.ui.box_drawing import draw_box
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.detail_screen import _USAGE_ICON_ROWS, DetailScreen, StatusBarInfo, UsageBar

key = pyglet.window.key


class NetworkScreen(DetailScreen):
    """The 'sys' Network panel: DetailScreen's lines and status bar as a
    full-height column on the left; on the right the traffic bars on top --
    only as tall as their interfaces need -- and below them a windowed
    program (see apps.window) filling the rest.

    The program is whatever `app_fn` returns -- for netman the one that's
    already running if there is one (see window_manager.running_app), so
    it's the same session and process as in its own window: same output,
    same history. This screen is its host while shown (the same host
    interface WindowManager provides): it's taken out of its window if it's
    shown in one, re-fitted to the box (the shell re-wraps its text), and
    handed back to the background when the screen closes -- 'netman' shows
    it in its window again. All input goes to it, except Escape, which
    closes the screen. 'exit' or 'quit' in it leave the box with a hint;
    Enter brings the program back (or starts a new one).

    The program is redrawn every `app_refresh_interval` seconds, so
    output that arrives later (e.g. ping's replies) shows up right away --
    the panel data stays on DetailScreen's slower refresh tick.

    `app_font_scale` below 1 shows the program in smaller text than the
    panel: it gets correspondingly more cols/rows than the box has and is
    drawn into it as the buffer's inset (see ScreenBuffer.set_inset), which
    the Renderer fills with glyphs that much smaller."""

    def __init__(self, buffer: ScreenBuffer, title: str, lines_fn: Callable[[], list[str]], screens: ScreenManager,
                 status_fn: Callable[[], StatusBarInfo], usage_fn: Callable[[], list[UsageBar]],
                 app_fn: Callable[[], object], usage_title: str = "Traffic",
                 usage_empty: str = "No network interfaces.", app_name: str = "netman",
                 app_refresh_interval: float = 0.1, app_font_scale: float = 1.0) -> None:
        self._app_fn = app_fn
        self._app_font_scale = app_font_scale
        self._app = None
        self._app_name = app_name
        self._app_refresh_interval = app_refresh_interval
        super().__init__(buffer, title, lines_fn(), screens, refresh=lines_fn, status_fn=status_fn,
                         usage_fn=usage_fn, usage_title=usage_title, usage_empty=usage_empty)

    # --- host interface (see apps.window) ---

    @property
    def screens(self) -> ScreenManager:
        return self._screens

    @property
    def main_buffer(self) -> ScreenBuffer:
        return self._buffer

    def is_active(self, window) -> bool:
        return self._screens.active is self and window is self._app and window.attached

    def close_window(self, window) -> None:
        """The program ended (quit, or its process was killed)."""
        window.closed()
        self._render_if_active()

    def detach_window(self, window) -> None:
        """The program wants to be hidden ('exit') -- it runs on in the background."""
        window.detached()
        self._render_if_active()

    @property
    def app(self):
        """The program shown in the box, or None."""
        return self._app if self._app is not None and self._app.attached else None

    # --- lifecycle ---

    def on_push(self) -> None:
        super().on_push()
        self._attach_app()
        self._render()
        pyglet.clock.schedule_interval(self._tick_app, self._app_refresh_interval)

    def on_pop(self) -> None:
        pyglet.clock.unschedule(self._tick_app)
        app = self.app
        if app is not None:  # back to the background, still running
            app.blur()
            app.detached()
        super().on_pop()

    def on_resume(self) -> None:
        """A full screen one of the program's commands opened was closed."""
        if self.app is not None:
            self.app.on_resume()
        self._render()

    def _attach_app(self) -> None:
        window = self._app_fn()
        if window.attached and window.keep_running:
            window.close()  # shown in its own window: hide it there, it moves in here
        self._app = window
        _, _, width, height = self._app_rect()
        window.open(self, *self._app_size(width, height))
        window.focus()

    def _tick_app(self, dt: float) -> None:
        if self._screens.active is not self or self.app is None:
            return
        self.app.update(dt)
        self._render()

    def _render_if_active(self) -> None:
        if self._screens.active is self:
            self._render()

    # --- drawing ---

    def _usage_height(self) -> int:
        """Border + padding row, the entries with a spacer row between them
        (see DetailScreen._render_usage), bottom border -- room for the
        empty message when there is no entry."""
        entries = sum(self._entry_rows(entry) + 1 for entry in self._usage) - 1
        return 3 + max(entries, 1)

    @staticmethod
    def _entry_rows(entry: UsageBar) -> int:
        """As DetailScreen._render_usage lays an entry out."""
        rows = 2 + len(entry.details)
        return max(_USAGE_ICON_ROWS, rows) if entry.sprite is not None else rows

    def _left_width(self) -> int:
        """A third of the screen -- wider if a line needs it, up to half."""
        cols = self._buffer.cols
        needed = max((len(line) for line in self._lines), default=0) + 4  # borders and padding
        return min(cols // 2, max(cols // 3, needed))

    def _app_rect(self) -> tuple[int, int, int, int]:
        cols, rows = self._buffer.cols, self._buffer.rows
        left_width = self._left_width()
        top = min(rows, self._usage_height())
        return left_width, top, cols - left_width, rows - top

    def _app_size(self, width: int, height: int) -> tuple[int, int]:
        """The program's size for a box of width x height cells -- more
        cells than the box has while its text is smaller (app_font_scale)."""
        return int(width / self._app_font_scale), int(height / self._app_font_scale)

    def _render(self) -> None:
        self._buffer.clear()
        cols, rows = self._buffer.cols, self._buffer.rows
        left_width = self._left_width()
        draw_box(self._buffer, 0, 0, left_width, rows, self._title, self._lines)
        self._render_status_bar(0, 0, left_width, rows)
        self._render_usage(left_width, 0, cols - left_width, min(rows, self._usage_height()))
        self._render_app(*self._app_rect())

    def _render_app(self, x: int, y: int, width: int, height: int) -> None:
        app = self.app
        if app is None:
            running = self._app is not None and self._app.is_open
            hint = (f"{self._app_name} runs in the background.", "Press Enter to show it here.") if running \
                else (f"{self._app_name} is not running.", "Press Enter to start it.")
            draw_box(self._buffer, x, y, width, height, self._app_name, list(hint))
            self._buffer.cursor_enabled = False
            return
        size = self._app_size(width, height)
        if app.size != size:
            app.resize(*size)  # e.g. the grid changed with the font size
        surface = app.surface
        cursor = app.cursor()
        if self._app_font_scale != 1.0:  # smaller text: drawn by the Renderer over the box
            surface.cursor_enabled = cursor is not None
            if cursor is not None:
                surface.cursor_col, surface.cursor_row = cursor
                surface.cursor_block = app.cursor_block
            self._buffer.set_inset(Inset(surface, x, y, width, height))
            self._buffer.cursor_enabled = False
            app.dirty = False
            return
        for row in range(min(height, surface.rows)):
            for col in range(min(width, surface.cols)):
                source = surface.get_cell(col, row)
                target = self._buffer.get_cell(x + col, y + row)
                target.char, target.fg_color, target.bg_color = source.char, source.fg_color, source.bg_color
        app.dirty = False
        self._buffer.cursor_enabled = cursor is not None
        if cursor is not None:
            self._buffer.cursor_col, self._buffer.cursor_row = x + cursor[0], y + cursor[1]
            self._buffer.cursor_block = app.cursor_block

    # --- input: everything to the program, except Escape ---

    def _forward(self, handler: str, *args) -> None:
        if self.app is not None:
            getattr(self.app, handler)(*args)
            self._render_if_active()

    def handle_text(self, text: str) -> None:
        self._forward("handle_text", text)

    def handle_motion(self, motion: int) -> None:
        self._forward("handle_motion", motion)

    def handle_motion_select(self, motion: int) -> None:
        self._forward("handle_motion_select", motion)

    def handle_enter(self) -> None:
        if self.app is None:  # gone: bring it back, or start a new one
            self._attach_app()
            self._render()
            return
        self.app.handle_enter()
        self._refresh_panel()  # a command (e.g. 'down eth0') shows in the panel at once, not on the next tick
        self._render_if_active()

    def _refresh_panel(self) -> None:
        """The panel's data, as DetailScreen._tick fetches it -- minus the blink."""
        self._lines = self._refresh()
        self._status = self._status_fn()
        self._usage = self._usage_fn()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
            return
        self._forward("handle_key", symbol, modifiers)
