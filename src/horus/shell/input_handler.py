from typing import Callable
from horus.display.screen_buffer import ScreenBuffer

import pyglet

class InputHandler:
    
    def __init__(self, buffer: ScreenBuffer, on_submit: Callable[[str], None] | None = None) -> None:
        self.cursor_col: int = 0
        self.cursor_row: int = 0
        self.buffer = buffer
        self.current_line: str = ""
        self._on_submit = on_submit
    
    def _advance_row(self, row_change: int) -> None:
        """Move the cursor down by row_change rows. If that would run past the last row,
        scroll the buffer up instead and pin the cursor to the last (bottom) row --
        this is what keeps new input visible at the bottom, like a classic terminal."""
        last_row = self.buffer.rows - 1
        new_row = self.cursor_row + row_change
        if new_row > last_row:
            self.buffer.scroll(direction='u', lines=(new_row - last_row))
            new_row = last_row
        self.cursor_row = new_row

    def _handle_text(self, text: str):
        if text is None:
            return
        text = "".join(char for char in text if char.isprintable())
        if not text:
            return
        self.buffer.write_string(col=self.cursor_col, row=self.cursor_row, string=text)
        self.current_line += text
        self.cursor_col = self.cursor_col + len(text)
        if self.cursor_col >= self.buffer.cols:
            row_change = self.cursor_col // self.buffer.cols
            self.cursor_col = self.cursor_col % self.buffer.cols
            self._advance_row(row_change)

    def _handle_motion(self, motion: int):
        if motion is None:
            return
        if motion == pyglet.window.key.MOTION_BACKSPACE:
            if len(self.current_line) == 0:
                return
            new_col = self.cursor_col - 1
            if new_col < 0:
                if self.cursor_row > 0:
                    self._advance_row(-1)
                    new_col = self.buffer.cols - 1
                else: 
                    return
            self.cursor_col = new_col
            self.current_line = self.current_line[:-1]
            self.buffer.write_char(col= self.cursor_col, row=self.cursor_row, char=" ")
            

    def _handle_enter(self):
        if self._on_submit is not None:
            self._on_submit(self.current_line)
        self.current_line = ""
        self.cursor_col = 0
        self._advance_row(1)
