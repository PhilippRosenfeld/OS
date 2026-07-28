from typing import Callable
from horus.display.screen_buffer import ScreenBuffer

import pyglet

class InputHandler:
    
    def __init__(self, buffer: ScreenBuffer, on_submit: Callable[[str], None] | None = None) -> None:
        self.buffer = buffer
        self.current_line: str = ""
        self._on_submit = on_submit
        self.insert_mode: bool = False
        self.line_cursor: int = 0
        self._sync_cursor()

    def _sync_cursor(self) -> None:
        """Sync the cursor state with the screen buffer:
        block cursor while in insert_mode (overwrite), thin bar otherwise. Also force it visible
        and mark the buffer dirty immediately, so a move/mode change is picked up right away
        instead of waiting for the next blink-timer tick."""
        self.buffer.cursor_visible = True
        self.buffer.cursor_block = self.insert_mode
        self.buffer.dirty = True

    def _advance_row(self, row_change: int) -> None:
        """Move the cursor down by row_change rows. If that would run past the last row,
        scroll the buffer up instead and pin the cursor to the last (bottom) row."""
        last_row = self.buffer.rows - 1
        new_row = self.buffer.cursor_row + row_change
        if new_row > last_row:
            self.buffer.scroll(direction='u', lines=(new_row - last_row))
            new_row = last_row
        self.buffer.cursor_row = new_row
        
    def _adjust_cursor(self, delta: int) -> None:
        """Move the cursor by `delta` columns (negative = left, positive = right),
        wrapping across row boundaries as needed. This is the shared col/row
        mechanic used. Moving past the bottom row scrolls the buffer (via _advance_row);
        moving before the very first cell clamps to (0, 0)."""
        row_change, new_col = divmod(self.buffer.cursor_col + delta, self.buffer.cols)
        if row_change > 0:
            self._advance_row(row_change)
        elif row_change < 0:
            new_row = self.buffer.cursor_row + row_change
            if new_row < 0:
                new_row, new_col = 0, 0
            self.buffer.cursor_row = new_row
        self.buffer.cursor_col = new_col
        self.line_cursor = max(0, min(len(self.current_line), self.line_cursor + delta))
        self._sync_cursor()

    def _handle_text(self, text: str):
        """Handles simple text input key presses, not correlating to any pyglet models."""
        if text is None:
            return
        text = "".join(char for char in text if char.isprintable())
        if not text:
            return
        if self.insert_mode:
            end = self.line_cursor + len(text)
            self.current_line = self.current_line[:self.line_cursor] + text + self.current_line[end:]
            self.buffer.write_string(col=self.cursor_col, row=self.cursor_row, string=text)
            self._adjust_cursor(len(text))
        else:
            tail = self.current_line[self.line_cursor:]
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=(text + tail))
            self.current_line = self.current_line[:self.line_cursor] + text + tail
            self._adjust_cursor(len(text))

    def _handle_motion(self, motion: int):
        """Handles key presses pyglet models as a text motion: Backspace, Left, Right, End..."""
        match motion:
            case None:
                return
            case pyglet.window.key.MOTION_BACKSPACE:
                if self.line_cursor == 0:
                    return
                tail = self.current_line[self.line_cursor:]
                self.current_line = self.current_line[:self.line_cursor - 1] + tail
                self._adjust_cursor(-1)
                self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=tail + " ")
            case pyglet.window.key.MOTION_LEFT:
                if self.line_cursor == 0:
                    return
                self._adjust_cursor(-1)
            case pyglet.window.key.MOTION_RIGHT:
                if self.line_cursor >= len(self.current_line):
                    return
                self._adjust_cursor(1)
            case pyglet.window.key.MOTION_BEGINNING_OF_LINE:
                self._adjust_cursor(-self.line_cursor)
                self.line_cursor = 0
            case pyglet.window.key.MOTION_END_OF_LINE:
                self._adjust_cursor(len(self.current_line) - self.line_cursor)
                self.line_cursor = len(self.current_line)
            case pyglet.window.key.MOTION_PREVIOUS_PAGE:
                self.buffer.scroll(direction="d", lines= self.buffer.rows // 2)
            case pyglet.window.key.MOTION_NEXT_PAGE:
                self.buffer.scroll(direction="u", lines= self.buffer.rows // 2) #TODO: text outside of screen is not getting saved

    def _handle_key(self, symbol: int, modifiers: int) -> None:
        """Handles key presses pyglet doesn't model as a text motion: Insert, Delete..."""
        if symbol == pyglet.window.key.INSERT:
            self.insert_mode = not self.insert_mode
            self._sync_cursor()
        if symbol == pyglet.window.key.DELETE:
            if self.line_cursor >= len(self.current_line):
                return
            tail = self.current_line[1 + self.line_cursor:]
            self.current_line = self.current_line[:self.line_cursor] + tail
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=tail + " ")
            

    def _handle_enter(self):
        """Handles enter key presses."""
        self._advance_row(1)
        if self._on_submit is not None:
            self._on_submit(self.current_line)
        self.current_line = ""
        self.line_cursor = 0
        self._sync_cursor()
