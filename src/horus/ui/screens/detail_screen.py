from dataclasses import dataclass
from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.box_drawing import draw_bar_chart, draw_box, draw_line_graph
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.settings_screen import SettingOption

key = pyglet.window.key


@dataclass(frozen=True)
class StatusBarInfo:
    """What DetailScreen's pinned bottom status bar (see `status_fn`) shows
    and how: `lit` off means it never highlights at all (e.g. a deactivated
    component -- nothing to warn about, so nothing lights up); `blink`
    makes a lit bar alternate with the tick like StatusBar's own warning
    lights, for states that need attention (e.g. a warning-level reading)
    without being as severe as a steady/critical one."""
    text: str
    lit: bool = True
    blink: bool = False


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
    its x-axis is always "Time". `history_unit` suffixes the current-reading
    display next to the graph's title (e.g. "C" or "W"). `history_markers_fn`, if given, is the same
    live-callable idea as `history_fn` but for the graph's dotted reference
    lines (e.g. warning/critical thresholds) -- a callable rather than a
    plain list since a threshold can itself change over time (e.g. the
    ambient/minimum-temperature marker). Leaving history_fn unset keeps
    today's single full-width box for every panel that doesn't have history
    to show yet.

    `options`, if given (and only together with history_fn -- it fills the
    otherwise-empty top-right box), is a list of SettingOption (the same
    type SettingScreen uses, with the same behavior): Up/Down moves the
    selection, Left/Right directly calls the selected option's on_left/
    on_right. `on_select`/Enter is unused here.

    `status_fn`, if given, is a live callable (same idiom as history_fn)
    returning a StatusBarInfo, pinned to its own bar centered at the very
    bottom of the left/main box, right above its border, with a horizontal
    rule above that -- like a small subpanel nested at the bottom, always
    in the same place regardless of how many regular `lines` came before
    it, rather than just another line that scrolls along with the rest.

    `breakdown_fn`, if given, switches to a different three-region layout
    instead of the one above: `lines` top left, the history graph top right
    (both half-height instead of full), and a `breakdown_title`-labeled box
    spanning the *full* width along the bottom, filled with whatever
    breakdown_fn returns -- e.g. a per-component power draw breakdown,
    where the full width actually helps fit every component on its own
    line. Only meaningful together with history_fn; options/status_fn are
    not supported in this layout since no panel has needed them here yet.

    `breakdown_chart_fn`, if given alongside breakdown_fn, splits that
    bottom box further: `breakdown_fn`'s text stays on its left half, and
    a bar chart of whatever breakdown_chart_fn returns -- a list of
    (label, value) pairs, e.g. the same per-component draws as the text,
    just visualized -- fills the right half (see draw_bar_chart). Leaving
    it unset keeps the breakdown box as plain full-width text."""

    def __init__(self, buffer: ScreenBuffer, title: str, lines: list[str], screens: ScreenManager,
                 refresh: Callable[[], list[str]] | None = None, refresh_interval: float = 1.0,
                 history_fn: Callable[[], list[float]] | None = None, history_title: str = "History",
                 history_y_label: str = "Value", history_unit: str = "",
                 history_markers_fn: Callable[[], list[float]] | None = None,
                 options: list[SettingOption] | None = None,
                 status_fn: Callable[[], StatusBarInfo] | None = None,
                 breakdown_fn: Callable[[], list[str]] | None = None, breakdown_title: str = "Breakdown",
                 breakdown_chart_fn: Callable[[], list[tuple[str, float]]] | None = None) -> None:
        self._buffer = buffer
        self._title = title
        self._lines = lines
        self._screens = screens
        self._refresh = refresh
        self._refresh_interval = refresh_interval
        self._history_fn = history_fn
        self._history_title = history_title
        self._history_y_label = history_y_label
        self._history_unit = history_unit
        self._history_markers_fn = history_markers_fn
        self._history_values = history_fn() if history_fn is not None else []
        self._history_markers = history_markers_fn() if history_markers_fn is not None else None
        self._options = options
        self._options_selected = 0
        self._status_fn = status_fn
        self._status = status_fn() if status_fn is not None else None
        self._status_blink_on = True  # only relevant while self._status.blink is True -- see _render_status_bar
        self._breakdown_fn = breakdown_fn
        self._breakdown_title = breakdown_title
        self._breakdown = breakdown_fn() if breakdown_fn is not None else []
        self._breakdown_chart_fn = breakdown_chart_fn
        self._breakdown_chart = breakdown_chart_fn() if breakdown_chart_fn is not None else []
        self._saved_screen: dict | None = None

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._buffer.clear()
        self._render()
        if (self._refresh is not None or self._history_fn is not None or self._history_markers_fn is not None
                or self._status_fn is not None or self._breakdown_fn is not None
                or self._breakdown_chart_fn is not None):
            pyglet.clock.schedule_interval(self._tick, self._refresh_interval)

    def on_pop(self) -> None:
        """restore() also brings back cursor_enabled from the snapshot, so this
        correctly leaves the cursor disabled when popping back into another menu
        instead of always re-enabling it as if the shell was always underneath."""
        if (self._refresh is not None or self._history_fn is not None or self._history_markers_fn is not None
                or self._status_fn is not None or self._breakdown_fn is not None
                or self._breakdown_chart_fn is not None):
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
        if self._status_fn is not None:
            self._status = self._status_fn()
            self._status_blink_on = not self._status_blink_on
        if self._breakdown_fn is not None:
            self._breakdown = self._breakdown_fn()
        if self._breakdown_chart_fn is not None:
            self._breakdown_chart = self._breakdown_chart_fn()
        self._render()

    def _render(self) -> None:
        # clear() also resets _writes -- see SettingScreen._render() for why
        # that matters once a resize (e.g. font size change) can happen while
        # this screen is showing.
        self._buffer.clear()
        cols, rows = self._buffer.cols, self._buffer.rows
        if self._history_fn is None:
            draw_box(self._buffer, 0, 0, cols, rows, self._title, self._lines)
            self._render_status_bar(0, 0, cols, rows)
            return

        left_width = cols // 2
        right_width = cols - left_width
        top_height = rows // 2
        bottom_height = rows - top_height

        if self._breakdown_fn is not None:
            draw_box(self._buffer, 0, 0, left_width, top_height, self._title, self._lines)
            self._render_status_bar(0, 0, left_width, top_height)
            draw_line_graph(self._buffer, left_width, 0, right_width, top_height,
                             self._history_title, self._history_values, y_label=self._history_y_label,
                             unit=self._history_unit, markers=self._history_markers)
            self._render_breakdown(0, top_height, cols, bottom_height)
            return

        draw_box(self._buffer, 0, 0, left_width, rows, self._title, self._lines)
        self._render_status_bar(0, 0, left_width, rows)
        if self._options:
            self._render_options(left_width, 0, right_width, top_height)
        else:
            draw_box(self._buffer, left_width, 0, right_width, top_height, "")  # reserved for later
        draw_line_graph(self._buffer, left_width, top_height, right_width, bottom_height,
                         self._history_title, self._history_values, y_label=self._history_y_label,
                         unit=self._history_unit, markers=self._history_markers)

    def _render_status_bar(self, x: int, y: int, width: int, height: int) -> None:
        """Overwrites the two rows right above the box's own bottom border
        (already drawn by draw_box) with a horizontal rule and a centered
        status strip -- called after draw_box, so it always wins over
        whatever regular content landed there. Highlighted (inverted) only
        while self._status.lit is True, and while blinking, only every
        other tick (self._status_blink_on) -- see StatusBarInfo."""
        if self._status_fn is None or width < 5 or height < 5:
            return
        divider_row = y + height - 3
        status_row = y + height - 2
        self._buffer.write_string(x, divider_row, f"+{'-' * (width - 2)}+")
        interior_width = width - 4
        text = self._status.text[:interior_width].center(interior_width)
        lit = self._status.lit and (self._status_blink_on if self._status.blink else True)
        if lit:
            self._buffer.write_string(x + 2, status_row, text, fg=self._buffer.default_bg, bg=self._buffer.default_fg)
        else:
            self._buffer.write_string(x + 2, status_row, text)

    def _render_breakdown(self, x: int, y: int, width: int, height: int) -> None:
        """Draws the breakdown box's border via draw_box, then writes
        `self._breakdown`'s text by hand (same clipping rules draw_box's
        own `lines` handling would have used) -- confined to the left half
        instead of the full interior when breakdown_chart_fn is given, to
        leave room for the bar chart on the right half."""
        draw_box(self._buffer, x, y, width, height, self._breakdown_title)
        if self._breakdown_chart_fn is None:
            interior_width = max(0, width - 4)
            for i, line in enumerate(self._breakdown):
                row = y + 2 + i
                if row >= y + height - 1:
                    break
                self._buffer.write_string(x + 2, row, line[:interior_width])
            return

        text_width = width // 2
        interior_width = max(0, text_width - 3)  # usual 2-col left pad, 1-col gap before the chart half
        for i, line in enumerate(self._breakdown):
            row = y + 2 + i
            if row >= y + height - 1:
                break
            self._buffer.write_string(x + 2, row, line[:interior_width])
        draw_bar_chart(self._buffer, x + text_width, y + 1, width - text_width - 1, height - 2, self._breakdown_chart)

    def _render_options(self, x: int, y: int, width: int, height: int) -> None:
        """Draws the border itself via draw_box, then writes each option's
        row by hand (like draw_line_graph does for its plot) since draw_box's
        own `lines` has no way to color just the selected row."""
        draw_box(self._buffer, x, y, width, height, "Options")
        interior_width = max(0, width - 4)
        for i, option in enumerate(self._options):
            row = y + 2 + i
            if row >= y + height - 1:
                break
            selected = i == self._options_selected
            marker = "> " if selected else "  "
            text = f"{marker}{option.label}: < {option.get_value()} >"[:interior_width]
            if selected:
                self._buffer.write_string(x + 2, row, text, fg=self._buffer.default_bg, bg=self._buffer.default_fg)
            else:
                self._buffer.write_string(x + 2, row, text)

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        if not self._options:
            return
        if motion == key.MOTION_UP:
            self._options_selected = (self._options_selected - 1) % len(self._options)
            self._render()
        elif motion == key.MOTION_DOWN:
            self._options_selected = (self._options_selected + 1) % len(self._options)
            self._render()
        elif motion in (key.MOTION_LEFT, key.MOTION_RIGHT):
            option = self._options[self._options_selected]
            handler = option.on_left if motion == key.MOTION_LEFT else option.on_right
            if handler is not None:
                handler()
            self._render()

    def handle_enter(self) -> None:
        pass

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
