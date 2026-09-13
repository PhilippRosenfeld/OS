from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key

_LEFT_TILE_COUNT = 3  # CPU, RAM, Storage


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
    the left, and one tall External tile on the right spanning the whole
    column (later home to sub-tiles like Energy/Cooling, once those exist).
    Up/Down move the selection within the left column, Left/Right jump
    between the two columns, Enter drills into the selected tile (see
    HardwareTile.on_select), Escape goes back to whatever screen was active
    before."""

    def __init__(self, buffer: ScreenBuffer, title: str, overview: HardwareTile, cpu: HardwareTile,
                 ram: HardwareTile, storage: HardwareTile, external: HardwareTile, screens: ScreenManager) -> None:
        self._buffer = buffer
        self._title = title
        self._overview = overview
        self._left_tiles = [cpu, ram, storage]
        self._external = external
        self._screens = screens
        self._selected_col = 0  # 0 = left column, 1 = external
        self._selected_row = 0  # index into _left_tiles; irrelevant while col == 1
        self._saved_screen: dict | None = None

    def on_push(self) -> None:
        self._saved_screen = self._buffer.snapshot()
        self._buffer.cursor_enabled = False
        self._buffer.clear()
        self._render()

    def on_pop(self) -> None:
        """restore() also brings back cursor_enabled from the snapshot, so this
        correctly leaves the cursor disabled when popping back into another menu
        instead of always re-enabling it as if the shell was always underneath."""
        self._buffer.restore(self._saved_screen)

    def _selected_tile(self) -> HardwareTile:
        return self._external if self._selected_col == 1 else self._left_tiles[self._selected_row]

    def _render(self) -> None:
        # clear() also resets _writes -- see SettingScreen._render() for why
        # that matters once a resize (e.g. font size change) can happen while
        # this screen is showing.
        self._buffer.clear()
        cols, rows = self._buffer.cols, self._buffer.rows

        header_height = min(rows, len(self._overview.lines) + 3)
        body_height = max(0, rows - header_height)
        col_width = cols // 2

        self._draw_tile(0, 0, cols, header_height, self._overview, selected=False)

        # Left column: CPU/RAM/Storage stacked, splitting the remaining
        # height as evenly as three rows allow -- any remainder goes to the
        # earlier tiles so the three heights never differ by more than 1.
        base_height = body_height // _LEFT_TILE_COUNT
        extra = body_height % _LEFT_TILE_COUNT
        y = header_height
        for i, tile in enumerate(self._left_tiles):
            height = base_height + (1 if i < extra else 0)
            self._draw_tile(0, y, col_width, height, tile, self._selected_col == 0 and self._selected_row == i)
            y += height

        # Right column: one tile spanning the whole body height.
        self._draw_tile(col_width, header_height, cols - col_width, body_height, self._external, self._selected_col == 1)

    def _draw_tile(self, x: int, y: int, width: int, height: int, tile: HardwareTile, selected: bool) -> None:
        """Draws a bordered box from (x, y) spanning width x height, with the
        tile's label embedded in the top border and its content lines inside.
        Every written string is clipped to the tile's own width first --
        ScreenBuffer.write_string wraps at the *buffer's* width when a string
        runs past it, not at any tile boundary, so an unclipped line would
        bleed into the next row instead of just being cut off."""
        if width < 2 or height < 2:
            return  # too small to even draw a border in
        fg = self._buffer.default_bg if selected else None
        bg = self._buffer.default_fg if selected else None

        border = f"+{'-' * (width - 2)}+"
        self._buffer.write_string(x, y, border, fg=fg, bg=bg)
        for row in range(y + 1, y + height - 1):
            self._buffer.write_string(x, row, "|", fg=fg, bg=bg)
            self._buffer.write_string(x + width - 1, row, "|", fg=fg, bg=bg)
        self._buffer.write_string(x, y + height - 1, border, fg=fg, bg=bg)

        label = f" {tile.label} "[:max(0, width - 2)]
        if label:
            self._buffer.write_string(x + 1, y, label, fg=fg, bg=bg)

        interior_width = max(0, width - 4)
        for i, line in enumerate(tile.lines):
            row = y + 2 + i
            if row >= y + height - 1:
                break
            self._buffer.write_string(x + 2, row, line[:interior_width])

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        if motion == key.MOTION_UP:
            if self._selected_col == 0:
                self._selected_row = (self._selected_row - 1) % _LEFT_TILE_COUNT
        elif motion == key.MOTION_DOWN:
            if self._selected_col == 0:
                self._selected_row = (self._selected_row + 1) % _LEFT_TILE_COUNT
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
            tile.on_select()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol == key.ESCAPE:
            self._screens.pop()
