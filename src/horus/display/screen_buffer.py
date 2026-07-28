from dataclasses import dataclass

@dataclass
class Cell: 
    """A Single character cell: What's shown and how """
    char: str = " "
    fg_color: tuple[int, int, int] = (0, 255, 0)  # Default foreground color: green
    bg_color: tuple[int, int, int] = (0, 0, 0)  # Default background color: black

class ScreenBuffer:
    """Class representing a screen buffer with a grid of cells. Renderer will read from this buffer to display content on the screen."""
    
    def __init__(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        self._cells: list[list[Cell]] = [[Cell() for _ in range(cols)] for _ in range(rows)]
        self._writes: list[tuple[int, int, str, tuple[int, int, int] | None, tuple[int, int, int] | None]] = []
        self.dirty = True
        self.cursor_col = 0
        self.cursor_row = 0
        self.cursor_visible = True
        self.cursor_block = True  # True: solid block cursor. False: thin bar cursor.
        self._scrollback: list[list[Cell]] = []
        self.view_offset = 0  # rows of scrollback shown at the top of the view instead of live content

    def write_char(self, col: int, row: int, char: str, fg: tuple[int, int, int] = None, bg: tuple[int, int, int] = None) -> None:
        """Write a character to the screen buffer at the specified column and row."""
        self.write_string(col, row, char, fg, bg) #TODO: Useless?

    def write_string(self, col: int, row: int, string: str, fg: tuple[int, int, int] = None, bg: tuple[int, int, int] = None) -> int:
        """Write a string to the screen buffer starting at the specified column and row,
        wrapping to subsequent rows instead of being cut off. Returns the number of
        rows the string spanned (>= 1), so callers can advance a cursor correctly."""
        self._writes.append((col, row, string, fg, bg))
        rows_used = self._place(col, row, string, fg, bg)
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
            if fg is not None:
                cell.fg_color = fg
            if bg is not None:
                cell.bg_color = bg
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
                    self._cells.append([Cell() for _ in range(self.cols)])
            case 'd':
                for _ in range(lines):
                    self._cells.pop()
                    self._cells.insert(0, [Cell() for _ in range(self.cols)])
            case 'l':
                for _ in range(lines):
                    for row in self._cells:
                        row.pop(0)
                        row.append(Cell())
            case 'r':
                for _ in range(lines):
                    for row in self._cells:
                        row.pop()
                        row.insert(0, Cell())
            case _:
                raise ValueError("Invalid scroll direction. Use 'u', 'd', 'l', or 'r'.")
        self.dirty = True

    def resize(self, cols: int, rows: int) -> None:
        """Resize the grid and re-wrap all previously written text to fit the new size, instead of losing content that no longer fits the old layout."""
        self.cols = cols
        self.rows = rows
        self._cells = [[Cell() for _ in range(cols)] for _ in range(rows)]
        self._scrollback = []  # old scrollback rows have the wrong width for the new self.cols
        writes, self._writes = self._writes, []
        for col, row, string, fg, bg in writes:
            self.write_string(col, row, string, fg, bg)
        self.dirty = True

    def clear(self) -> None:
        """Clear the screen buffer by resetting all cells to default."""
        self._cells = [[Cell() for _ in range(self.cols)] for _ in range(self.rows)]
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
        
    