from dataclasses import dataclass

from horus.display.colors import NAMED_COLORS


@dataclass
class Cell: 
    """A Single character cell: What's shown and how """
    char: str = " "
    fg_color: tuple[int, int, int] = NAMED_COLORS.get("green")  # Placeholder foreground color: will be overwritten
    bg_color: tuple[int, int, int] = NAMED_COLORS.get("magenta")  # Placeholder background color: will be overwritten

class ScreenBuffer:
    """Class representing a screen buffer with a grid of cells. Renderer will read from this buffer to display content on the screen."""
    
    def __init__(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        self._writes: list[tuple[int, int, str, tuple[int, int, int] | None, tuple[int, int, int] | None]] = []
        self.dirty = True
        self.cursor_col = 0
        self.cursor_row = 0
        self.cursor_visible = True
        self.cursor_enabled = True  # False: cursor never renders, regardless of the blink state above
        self.cursor_block = True  # True: solid block cursor. False: thin bar cursor.
        self._scrollback: list[list[Cell]] = []
        self.view_offset = 0  # rows of scrollback shown at the top of the view instead of live content
        self.default_fg: tuple[int, int, int] = NAMED_COLORS.get("green")
        self.default_bg: tuple[int, int, int] = NAMED_COLORS.get("black")
        self._cells: list[list[Cell]] = [[self._blank_cell() for _ in range(cols)] for _ in range(rows)] #has to be set after colors!

    def write_char(self, col: int, row: int, char: str, fg: tuple[int, int, int] = None, bg: tuple[int, int, int] = None) -> None:
        """Write a character to the screen buffer at the specified column and row."""
        self.write_string(col, row, char, fg, bg) #TODO: Useless?

    def write_string(self, col: int, row: int, string: str, fg: tuple[int, int, int] = None, bg: tuple[int, int, int] = None) -> int:
        """Write a string to the screen buffer starting at the specified column and row,
        wrapping to subsequent rows instead of being cut off. Returns the number of
        rows the string spanned (>= 1), so callers can advance a cursor correctly."""
        resolved_fg = fg if fg is not None else self.default_fg
        resolved_bg = bg if bg is not None else self.default_bg
        self._writes.append((col, row, string, resolved_fg, resolved_bg))
        rows_used = self._place(col, row, string, resolved_fg, resolved_bg)
        self.view_offset = 0  # any new content snaps the view back to live, like a real terminal
        self.dirty = True
        return rows_used

    def _place(self, col: int, row: int, string: str, fg: tuple[int, int, int] = None, bg: tuple[int, int, int] = None) -> int:
        """Write a string into the current grid, wrapping to the next row when a line
        is full. Returns the number of rows touched, clamped to the buffer's bounds."""
        if col < 0 or row < 0:
            return 0
        start_row = row
        for char in string:
            if col >= self.cols:
                col = 0
                row += 1
            if row >= self.rows:
                break
            cell = self._cells[row][col]
            cell.char = char
            cell.fg_color = fg if fg is not None else self.default_fg
            cell.bg_color = bg if bg is not None else self.default_bg
            col += 1
        end_row = min(row, self.rows - 1)
        return end_row - start_row + 1

    def scroll(self, direction: str, lines: int) -> None:
        """Scroll the screen buffer in the specified direction ('u', 'd', 'l', 'r') for a given number of lines.
        Rows pushed off the top ('u') are kept in a scrollback history instead of being discarded --
        see scroll_view() to navigate back into them (e.g. Page Up/Down) without touching live content."""
        match direction:
            case 'u':
                for _ in range(lines):
                    self._scrollback.append(self._cells.pop(0))
                    self._cells.append([self._blank_cell() for _ in range(self.cols)])
            case 'd':
                for _ in range(lines):
                    self._cells.pop()
                    self._cells.insert(0, [self._blank_cell() for _ in range(self.cols)])
            case 'l':
                for _ in range(lines):
                    for row in self._cells:
                        row.pop(0)
                        row.append(self._blank_cell())
            case 'r':
                for _ in range(lines):
                    for row in self._cells:
                        row.pop()
                        row.insert(0, self._blank_cell())
            case _:
                raise ValueError("Invalid scroll direction. Use 'u', 'd', 'l', or 'r'.")
        self.dirty = True

    def resize(self, cols: int, rows: int) -> None:
        """Resize the grid and re-wrap all previously written text to fit the new size, instead of losing content that no longer fits the old layout."""
        self.cols = cols
        self.rows = rows
        self._cells = [[self._blank_cell() for _ in range(cols)] for _ in range(rows)]
        self._scrollback = []  # old scrollback rows have the wrong width for the new self.cols
        writes, self._writes = self._writes, []
        for col, row, string, fg, bg in writes:
            self.write_string(col, row, string, fg, bg)
        self.dirty = True

    def clear(self) -> None:
        """Clear the screen buffer by resetting all cells to default."""
        self._cells = [[self._blank_cell() for _ in range(self.cols)] for _ in range(self.rows)]
        self._writes = []
        self._scrollback = []
        self.view_offset = 0
        self.dirty = True

    def scroll_view(self, delta: int) -> None:
        """Move the view into scrollback history by `delta` rows (positive = further into
        the past, negative = back toward the live edge). Clamped to available history and
        the live view. Does not touch the underlying live content -- only what's displayed."""
        self.view_offset = max(0, min(len(self._scrollback), self.view_offset + delta))
        self.dirty = True

    def get_cell(self, col: int, row: int) -> Cell:
        """Get the cell at the specified column and row, accounting for view_offset:
        when scrolled back into history, earlier rows come from scrollback and later
        rows from the live grid, blended at the point where the two meet."""
        if self.view_offset == 0:
            return self._cells[row][col]
        combined_index = len(self._scrollback) - self.view_offset + row
        if 0 <= combined_index < len(self._scrollback):
            return self._scrollback[combined_index][col]
        return self._cells[combined_index - len(self._scrollback)][col]
        
    def set_default_color(self, fg=None, bg=None):
        """Sets the colors used for future writes. Foreground applies only to
        subsequent writes. Background is applied immediately to every cell from
        the current cursor position onward (the current row from cursor_col on,
        and every row below) -- cells before the cursor are left untouched."""
        if fg is not None:
            self.default_fg = fg
        if bg is not None:
            self.default_bg = bg
            for row_idx in range(self.cursor_row, self.rows):
                start_col = self.cursor_col if row_idx == self.cursor_row else 0
                for col_idx in range(start_col, self.cols):
                    self._cells[row_idx][col_idx].bg_color = bg
            self.dirty = True

    def recolor_all(self, fg=None, bg=None):
        """Recolors the entire terminal, including scrollback history (e.g. lines only reachable via Page Up)."""
        for row in (*self._cells, *self._scrollback):
            for cell in row:
                if fg is not None:
                    cell.fg_color= fg
                if bg is not None:
                    cell.bg_color= bg
        self.dirty=True
    
    def snapshot(self) -> dict:
        """Capture the visible grid + cursor position so it can be restored later
        (e.g. a menu overlay that temporarily takes over the screen). Includes
        _writes -- the replay log resize() uses -- so that a later resize() while
        the restored content is showing re-wraps *this* content, not whatever the
        overlay itself wrote in the meantime (overlays clear() on their way in,
        which wipes _writes, and keep appending to it as they re-render)."""
        return {
            "cols": self.cols,
            "rows": self.rows,
            "cells": [[Cell(c.char, c.fg_color, c.bg_color) for c in row] for row in self._cells],
            "writes": list(self._writes),
            "cursor_col": self.cursor_col,
            "cursor_row": self.cursor_row,
            "cursor_enabled": self.cursor_enabled,
            "view_offset": self.view_offset,
        }

    def restore(self, snapshot: dict) -> None:
        """Restore a grid + cursor position previously captured with snapshot(). If
        cols/rows changed since the snapshot was taken (e.g. a settings menu resized
        the window or font while active), the saved cells are fitted -- padded or
        clipped -- to the current grid instead of being swapped in as-is, since a raw
        swap would leave _cells out of sync with cols/rows."""
        cells = snapshot["cells"]
        if snapshot["cols"] != self.cols or snapshot["rows"] != self.rows:
            cells = [
                [
                    cells[r][c] if r < len(cells) and c < len(cells[r]) else self._blank_cell()
                    for c in range(self.cols)
                ]
                for r in range(self.rows)
            ]
        self._cells = cells
        self._writes = list(snapshot["writes"])
        self.cursor_col = min(snapshot["cursor_col"], self.cols - 1)
        self.cursor_row = min(snapshot["cursor_row"], self.rows - 1)
        self.cursor_enabled = snapshot["cursor_enabled"]
        self.view_offset = snapshot["view_offset"]
        self.dirty = True

    def _blank_cell(self) -> Cell:
        """A fresh empty cell using the buffer's current default colors,
        so newly created cells (init, scroll, resize, clear) always match
        whatever set_default_colors() last configured."""
        return Cell(char=" ", fg_color=self.default_fg, bg_color=self.default_bg)