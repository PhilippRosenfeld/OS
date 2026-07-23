from dataclasses import dataclass

@dataclass
class Cell: 
    """A Single character cell: What's shown and how """
    char: str = " "
    fg_color: tuple[int, int, int] = (255, 255, 255)  # Default foreground color: white
    bg_color: tuple[int, int, int] = (0, 0, 0)  # Default background color: black

class ScreenBuffer:
    """Class representing a screen buffer with a grid of cells. Renderer will read from this buffer to display content on the screen."""
    
    def __init__(self, cols: int, rows: int) -> None:
        self.cols = cols
        self.rows = rows
        self._cells: list[list[Cell]] = [[Cell() for _ in range(cols)] for _ in range(rows)]
        
    def write_char(self, col: int, row: int, char: str, fg: tuple[int, int, int] = None, bg: tuple[int, int, int] = None) -> None:
        """Write a character to the screen buffer at the specified column and row."""
        if 0 <= col < self.cols and 0 <= row < self.rows:
            cell = self._cells[row][col]
            cell.char = char
            if fg is not None:
                cell.fg_color = fg
            if bg is not None:
                cell.bg_color = bg
        
    def write_string(self, col: int, row: int, string: str, fg: tuple[int, int, int] = None, bg: tuple[int, int, int] = None) -> None:
        """Write a string to the screen buffer starting at the specified column and row."""
        for i, char in enumerate(string):
            if col + i < self.cols:
                self.write_char(col + i, row, char, fg, bg)
            else: 
                break  # Stop writing if we exceed the column limit TODO: Handle wrapping to the next line if needed
        
    def scroll(self, direction: str, lines: int) -> None:
        """Scroll the screen buffer in the specified direction ('u', 'd', 'l', 'r') for a given number of lines."""
        match direction:
            case 'u':
                for _ in range(lines):
                    self._cells.pop(0)
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
            
    def clear(self) -> None:
        """Clear the screen buffer by resetting all cells to default."""
        self._cells = [[Cell() for _ in range(self.cols)] for _ in range(self.rows)]
        
    def get_cell(self, col: int, row: int) -> Cell:
        """Get the cell at the specified column and row."""
        return self._cells[row][col]
        
    