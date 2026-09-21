from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.box_drawing import draw_box
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key

_LEFT_TILE_COUNT = 3   # CPU, RAM, Storage
_RIGHT_TILE_COUNT = 3  # Power, Cooling, Network -- nested inside the External tile


class HardwareTile:
    """One tile in the hardware overview: a title shown in its border and a
    few lines of content. `on_select` fires on Enter while this tile is
    selected -- nothing wires it up yet (no detail panels exist), it's just
    here so a later drill-down view only needs to pass a callback in."""

    def __init__(self, label: str, lines: list[str] | None = None, on_select: Callable[[], None] | None = None) -> None:
        self.label = label
        self.lines = lines or []
        self.on_select = on_select


class HardwareScreen(Screen):
    """Overview of the simulated system's hardware: a full-width summary bar
    across the top, then two columns below it -- CPU/RAM/Storage stacked on
    the left, and one External tile on the right spanning the whole column,
    with Power/Cooling/Network nested inside it as smaller sub-tiles. Up/Down
    move the selection within the current column (the outer External tile
    itself isn't selectable, only its nested sub-tiles are), Left/Right jump
    between the two columns, Enter drills into the selected tile (see
    HardwareTile.on_select), Escape goes back to whatever screen was active
    before.

    `refresh`, if given, is called (with no arguments) every `refresh_interval`
    seconds -- like TopScreen, but generalized: HardwareScreen doesn't know
    about ProcessTable/HardwareSpec, so the caller's `refresh` callback is
    expected to mutate the tiles' own `.lines` in place (they're the same
    objects passed into the constructor) with fresh data; this screen just
    re-renders afterwards. Leaving `refresh` unset keeps the tiles static,
    same as before this existed."""

    def __init__(self, buffer: ScreenBuffer, title: str, overview: HardwareTile, cpu: HardwareTile,
                 ram: HardwareTile, storage: HardwareTile, external: HardwareTile, power: HardwareTile,
                 cooling: HardwareTile, network: HardwareTile, screens: ScreenManager,
                 refresh: Callable[[], None] | None = None, refresh_interval: float = 1.0) -> None:
        self._buffer = buffer
        self._title = title
        self._overview = overview
        self._external = external
        self._columns = [[cpu, ram, storage], [power, cooling, network]]
        self._screens = screens
        self._refresh = refresh
        self._refresh_interval = refresh_interval
        self._selected_col = 0  # 0 = left column, 1 = External's nested sub-tiles
        self._selected_row = 0  # index into the selected column's tiles
        self._saved_screen: dict | None = None

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._buffer.clear()
        self._render()
        if self._refresh is not None:
            pyglet.clock.schedule_interval(self._tick, self._refresh_interval)

    def on_pop(self) -> None:
        """restore() also brings back cursor_enabled from the snapshot, so this
        correctly leaves the cursor disabled when popping back into another menu
        instead of always re-enabling it as if the shell was always underneath."""
        if self._refresh is not None:
            pyglet.clock.unschedule(self._tick)
        self._buffer.restore(self._saved_screen)

    def on_resume(self) -> None:
        """Called when a tile's detail screen (pushed on top of us by
        handle_enter(), see below) pops back off -- restart the ticking that
        was paused for it, and redraw immediately so nothing here looks
        stale after however long the detail screen was open."""
        if self._refresh is not None:
            self._refresh()
            pyglet.clock.schedule_interval(self._tick, self._refresh_interval)
        self._render()

    def _tick(self, dt: float) -> None:
        """Guarded, not just paused via handle_enter()'s unschedule: a screen
        can also end up covering us from outside our own code entirely (e.g.
        a CrashScreen pushed by a temperature/power event reaction while
        we're active) -- without this check, our own tick keeps clobbering
        its content on the shared buffer every interval, making it flicker
        in and out instead of staying put."""
        if self._screens.active is not self:
            return
        self._refresh()
        self._render()

    def _selected_tile(self) -> HardwareTile:
        return self._columns[self._selected_col][self._selected_row]

    def _tile_count(self, col_index: int) -> int:
        return _LEFT_TILE_COUNT if col_index == 0 else _RIGHT_TILE_COUNT

    def _render(self) -> None:
        # clear() also resets _writes -- see SettingScreen._render() for why
        # that matters once a resize (e.g. font size change) can happen while
        # this screen is showing.
        self._buffer.clear()
        cols, rows = self._buffer.cols, self._buffer.rows

        header_height = min(rows, len(self._overview.lines) + 3)
        body_height = max(0, rows - header_height)
        col_width = cols // 2
        external_width = cols - col_width

        self._draw_tile(0, 0, cols, header_height, self._overview, selected=False)

        # Left column: CPU/RAM/Storage stacked directly across the full column.
        self._draw_column(0, header_height, col_width, body_height, col_index=0)

        # Right column: the External tile spans the whole column; Power/
        # Cooling/Network are drawn nested inside its interior (inset by 1
        # cell on every side for External's own border).
        self._draw_tile(col_width, header_height, external_width, body_height, self._external, selected=False)
        self._draw_column(col_width + 1, header_height + 1, max(0, external_width - 2), max(0, body_height - 2), col_index=1)

    def _draw_column(self, x: int, y: int, width: int, height: int, col_index: int) -> None:
        """Stacks a column's tiles top to bottom, splitting the available
        height as evenly as they allow -- any remainder goes to the earlier
        tiles so heights never differ by more than 1 row."""
        tiles = self._columns[col_index]
        tile_count = self._tile_count(col_index)
        base_height = height // tile_count
        extra = height % tile_count
        row_y = y
        for row_index, tile in enumerate(tiles):
            tile_height = base_height + (1 if row_index < extra else 0)
            selected = self._selected_col == col_index and self._selected_row == row_index
            self._draw_tile(x, row_y, width, tile_height, tile, selected)
            row_y += tile_height

    def _draw_tile(self, x: int, y: int, width: int, height: int, tile: HardwareTile, selected: bool) -> None:
        draw_box(self._buffer, x, y, width, height, tile.label, tile.lines, selected)

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        tile_count = self._tile_count(self._selected_col)
        if motion == key.MOTION_UP:
            self._selected_row = (self._selected_row - 1) % tile_count
        elif motion == key.MOTION_DOWN:
            self._selected_row = (self._selected_row + 1) % tile_count
        elif motion == key.MOTION_LEFT:
            self._selected_col = 0
        elif motion == key.MOTION_RIGHT:
            self._selected_col = 1
        else:
            return
        self._render()

    def handle_enter(self) -> None:
        tile = self._selected_tile()
        if tile.on_select is not None:
            # About to hand off to the tile's detail screen (that's what
            # on_select does) -- pause our own ticking while it's covering
            # us, or our periodic _render() would keep clobbering its
            # content on the same shared buffer (see on_resume(), which
            # restarts it once we're active again).
            if self._refresh is not None:
                pyglet.clock.unschedule(self._tick)
            tile.on_select()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
