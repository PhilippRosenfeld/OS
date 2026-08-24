from typing import Callable
from horus.display.screen_buffer import ScreenBuffer
from horus.session.history import CommandHistory

import pyglet
import logging

logger = logging.getLogger(__name__)

class InputHandler:
    
    def __init__(self, buffer: ScreenBuffer, history: CommandHistory, on_submit: Callable[[str], None] | None = None, get_prompt: Callable[[], str] | None = None) -> None:
        self.buffer = buffer
        self.history = history
        self.current_line: str = ""
        self._on_submit = on_submit
        self._get_prompt = get_prompt
        self.insert_mode: bool = False
        self.line_cursor: int = 0
        self.start_line()

    def start_line(self) -> None:
        """Write the prompt (e.g. 'user@cwd > ') at the start of the current row, if a
        get_prompt callback was given, and position the cursor right after it, ready
        for input. Called for the very first line and after every submitted line --
        but the caller decides *when* it's safe to call this (e.g. ShellScreen skips
        it if the submitted command switched to a different screen, since writing
        here would otherwise clobber whatever that screen just rendered)."""
        prompt = self._get_prompt() if self._get_prompt is not None else ""
        if prompt:
            self.buffer.write_string(col=0, row=self.buffer.cursor_row, string=prompt)
        self.buffer.cursor_col = len(prompt)
        self.line_cursor = 0
        self._sync_cursor()

    def _sync_cursor(self) -> None:
        """Mirror our cursor position and mode onto the ScreenBuffer so the Renderer can draw it:
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

    def _next_word_boundary(self) -> int:
        """Return the current_line index at the start of the next word from line_cursor."""
        i = self.line_cursor
        n = len(self.current_line)
        while i < n and self.current_line[i].isalnum():  # skip rest of the current word
            i += 1
        while i < n and not self.current_line[i].isalnum():  # skip the gap to the next word
            i += 1
        return i

    def _previous_word_boundary(self) -> int:
        """Return the current_line index at the start of the previous word from line_cursor."""
        i = self.line_cursor
        while i > 0 and not self.current_line[i - 1].isalnum():  # skip the gap before the cursor
            i -= 1
        while i > 0 and self.current_line[i - 1].isalnum():  # skip the previous word
            i -= 1
        return i

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
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=text)
            self._adjust_cursor(len(text))
        else:
            tail = self.current_line[self.line_cursor:]
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=(text + tail))
            self.current_line = self.current_line[:self.line_cursor] + text + tail
            self._adjust_cursor(len(text))

    def _handle_motion(self, motion: int):
        """Handles key presses pyglet models as a text motion: Backspace, Left, Right, End..."""
        logger.debug(f"INPUT: Motion='{motion}'")
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

            case pyglet.window.key.MOTION_UP:
                entry = self.history.previous(self.current_line)
                if entry is not None:
                    self._replace_current_line(entry)

            case pyglet.window.key.MOTION_DOWN:
                entry = self.history.next()
                if entry is not None:
                    self._replace_current_line(entry)
   
            case pyglet.window.key.MOTION_BEGINNING_OF_LINE:
                self._adjust_cursor(-self.line_cursor)
                self.line_cursor = 0
                
            case pyglet.window.key.MOTION_END_OF_LINE:
                self._adjust_cursor(len(self.current_line) - self.line_cursor)
                self.line_cursor = len(self.current_line)
            
            case pyglet.window.key.MOTION_PREVIOUS_PAGE:  # Page Up: look further back into scrollback history
                self.buffer.scroll_view(self.buffer.rows // 3)

            case pyglet.window.key.MOTION_NEXT_PAGE:  # Page Down: move back toward the live view
                self.buffer.scroll_view(-(self.buffer.rows // 3))

            case pyglet.window.key.MOTION_NEXT_WORD:
                self._adjust_cursor(self._next_word_boundary() - self.line_cursor)

            case pyglet.window.key.MOTION_PREVIOUS_WORD:
                self._adjust_cursor(self._previous_word_boundary() - self.line_cursor)

    def _handle_key(self, symbol: int, modifiers: int) -> None:
        """Handles key presses pyglet doesn't model as a text motion: Insert, Delete..."""
        logger.debug(f"INPUT: Symbol='{symbol}', modifiers='{modifiers}'")
        ctrl_held = bool(modifiers & pyglet.window.key.MOD_CTRL)
        
        if symbol == pyglet.window.key.INSERT:
            self.insert_mode = not self.insert_mode
            self._sync_cursor()
        
        elif symbol == pyglet.window.key.DELETE and ctrl_held:
            end = self._next_word_boundary()
            if end == self.line_cursor:
                return
            deleted = end - self.line_cursor
            tail = self.current_line[end:]
            self.current_line = self.current_line[:self.line_cursor] + tail
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=tail + " " * deleted)
        
        elif symbol == pyglet.window.key.DELETE:
            if self.line_cursor >= len(self.current_line):
                return
            tail = self.current_line[1 + self.line_cursor:]
            self.current_line = self.current_line[:self.line_cursor] + tail
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=tail + " ")
            
        elif symbol == pyglet.window.key.BACKSPACE and ctrl_held:
            start = self._previous_word_boundary()
            if start == self.line_cursor:
                return
            deleted = self.line_cursor - start
            tail = self.current_line[self.line_cursor:]
            self.current_line = self.current_line[:start] + tail
            self._adjust_cursor(start - self.line_cursor)
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=tail + " " * deleted)
            

    def _handle_enter(self):
        """Handles enter key presses. Leaves writing the prompt for the next line to
        start_line() -- see its docstring for why that's the caller's decision."""
        logger.debug(f"INPUT: 'enter', Current Line='{self.current_line}")
        self._advance_row(1)
        self.buffer.cursor_col = 0
        self._sync_cursor()

        if self.current_line.strip():
            self.history.add(self.current_line)

        if self._on_submit is not None:
            self._on_submit(self.current_line)

        self.current_line = ""
        self.line_cursor = 0
        self._sync_cursor()

    def _replace_current_line(self, new_line: str) -> None:
        old_len = len(self.current_line)
        start_col = self.buffer.cursor_col - self.line_cursor

        # Overwrite the old line's screen area with blanks first
        self.buffer.write_string(col=start_col, row=self.buffer.cursor_row, string=" " * old_len)

        self.current_line = new_line
        self.buffer.write_string(col=start_col, row=self.buffer.cursor_row, string=new_line)

        self.buffer.cursor_col = start_col
        self.line_cursor = 0
        self._adjust_cursor(len(new_line))