from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.box_drawing import draw_box, draw_line_graph
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key


class DetailScreen(Screen):
    """Generic full-panel detail view: one bordered box spanning the whole
    buffer, with a title and a list of lines. Escape pops back. Used both
    for a single hardware component (opened by pressing Enter on one of
    HardwareScreen's tiles, see HardwareTile.on_select) and for the 'err'
    command's warning/error log.

    `refresh`, if given, is called (with no arguments) every `refresh_interval`
    seconds and must return a fresh list of lines to display -- the same
    live-refresh idiom HardwareScreen itself uses (see TopScreen), so live
    values (load, draw, temperature, new log entries, ...) don't go stale
    while this screen stays open. Leaving `refresh` unset keeps the lines
    static.

    `history_fn`, if given, switches the layout to three regions instead of
    one full-width box: `lines` on the left (unchanged), an empty box top
    right (reserved for something later), and a `history_title`-labeled line
    graph bottom right plotting whatever `history_fn` returns (oldest first,
    e.g. a MetricHistory.values()) -- called on the same refresh_interval
    tick as `refresh`, so it stays as live as the lines do (new samples
    enter the graph from the right and scroll left as they age -- see
    draw_line_graph). `history_y_label` becomes the graph's y-axis label;
    its x-axis is always "Time". `history_markers_fn`, if given, is the same
    live-callable idea as `history_fn` but for the graph's dotted reference
    lines (e.g. warning/critical thresholds) -- a callable rather than a
    plain list since a threshold can itself change over time (e.g. the
    ambient/minimum-temperature marker). Leaving history_fn unset keeps
    today's single full-width box for every panel that doesn't have history
    to show yet."""

    def __init__(self, buffer: ScreenBuffer, title: str, lines: list[str], screens: ScreenManager,
                 refresh: Callable[[], list[str]] | None = None, refresh_interval: float = 1.0,
                 history_fn: Callable[[], list[float]] | None = None, history_title: str = "History",
                 history_y_label: str = "Value",
                 history_markers_fn: Callable[[], list[float]] | None = None) -> None:
        self._buffer = buffer
        self._title = title
        self._lines = lines
        self._screens = screens
        self._refresh = refresh
        self._refresh_interval = refresh_interval
        self._history_fn = history_fn
        self._history_title = history_title
        self._history_y_label = history_y_label
        self._history_markers_fn = history_markers_fn
        self._history_values = history_fn() if history_fn is not None else []
        self._history_markers = history_markers_fn() if history_markers_fn is not None else None
        self._saved_screen: dict | None = None

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._buffer.clear()
        self._render()
        if self._refresh is not None or self._history_fn is not None or self._history_markers_fn is not None:
            pyglet.clock.schedule_interval(self._tick, self._refresh_interval)

    def on_pop(self) -> None:
        """restore() also brings back cursor_enabled from the snapshot, so this
        correctly leaves the cursor disabled when popping back into another menu
        instead of always re-enabling it as if the shell was always underneath."""
        if self._refresh is not None or self._history_fn is not None or self._history_markers_fn is not None:
            pyglet.clock.unschedule(self._tick)
        self._buffer.restore(self._saved_screen)

    def _tick(self, dt: float) -> None:
        """Guarded against ticking while covered by something pushed on top
        of us from outside our own code (e.g. a CrashScreen from a
        temperature/power event reaction) -- see HardwareScreen._tick for
        why this can't just rely on our own on_push()/on_pop()."""
        if self._screens.active is not self:
            return
        if self._refresh is not None:
            self._lines = self._refresh()
        if self._history_fn is not None:
            self._history_values = self._history_fn()
        if self._history_markers_fn is not None:
            self._history_markers = self._history_markers_fn()
        self._render()

    def _render(self) -> None:
        # clear() also resets _writes -- see SettingScreen._render() for why
        # that matters once a resize (e.g. font size change) can happen while
        # this screen is showing.
        self._buffer.clear()
        cols, rows = self._buffer.cols, self._buffer.rows
        if self._history_fn is None:
            draw_box(self._buffer, 0, 0, cols, rows, self._title, self._lines)
            return

        left_width = cols // 2
        right_width = cols - left_width
        top_height = rows // 2
        bottom_height = rows - top_height
        draw_box(self._buffer, 0, 0, left_width, rows, self._title, self._lines)
        draw_box(self._buffer, left_width, 0, right_width, top_height, "")  # reserved for later
        draw_line_graph(self._buffer, left_width, top_height, right_width, bottom_height,
                         self._history_title, self._history_values, y_label=self._history_y_label,
                         markers=self._history_markers)

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        pass

    def handle_enter(self) -> None:
        pass

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
