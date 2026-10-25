import logging
from typing import Callable

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.session.history import CommandHistory
from horus.shell.clipboard import Clipboard

logger = logging.getLogger(__name__)

key = pyglet.window.key

# Text motions that only move the cursor -- with Shift held (see
# _handle_motion_select) they extend the selection instead.
_CURSOR_MOTIONS = (
    key.MOTION_LEFT, key.MOTION_RIGHT,
    key.MOTION_BEGINNING_OF_LINE, key.MOTION_END_OF_LINE,
    key.MOTION_PREVIOUS_WORD, key.MOTION_NEXT_WORD,
)


class InputHandler:
    """Line editing for a shell prompt: typing, cursor movement, history,
    Tab completion -- and selecting part of the line with Shift (+ arrows,
    Home/End, Ctrl for whole words), shown inverted, which Ctrl+C copies,
    Ctrl+X cuts, typing/Backspace/Delete replace and Ctrl+A selects all of.
    Ctrl+V pastes. `clipboard` is shared with whatever else copies/pastes
    (see shell.clipboard) -- without one, a private in-memory clipboard."""

    def __init__(self, buffer: ScreenBuffer, history: CommandHistory, on_submit: Callable[[str], None] | None = None,
                 get_prompt: Callable[[], str] | None = None, complete: Callable[[str], list[str]] | None = None,
                 clipboard: Clipboard | None = None) -> None:
        self.buffer = buffer
        self.history = history
        self.current_line: str = ""
        self._on_submit = on_submit
        self._get_prompt = get_prompt
        self._complete = complete  # word (prefix) -> sorted list of candidate replacements; None disables Tab completion
        self.clipboard = clipboard if clipboard is not None else Clipboard()
        self.selection_anchor: int | None = None  # line index where the selection started; None = nothing selected
        self.insert_mode: bool = False
        self.line_cursor: int = 0
        self.start_line()
        self._pending_submit: Callable[[str], None] | None = None
        self.masked: bool = False
        self._tab_word_start: int | None = None
        self._tab_candidates: list[str] = []
        self._tab_index: int = -1
        self._tab_press_count: int = 0
        self._sync_cursor()


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
        self.selection_anchor = None
        self._sync_cursor()

    # --- selection ---

    @property
    def selection(self) -> tuple[int, int] | None:
        """(start, end) of the selected part of current_line, end exclusive --
        or None when nothing is selected."""
        if self.selection_anchor is None or self.selection_anchor == self.line_cursor:
            return None
        return min(self.selection_anchor, self.line_cursor), max(self.selection_anchor, self.line_cursor)

    @property
    def selected_text(self) -> str:
        selection = self.selection
        return self.current_line[selection[0]:selection[1]] if selection is not None else ""

    def _position_of(self, index: int) -> tuple[int, int]:
        """(col, row) on screen of current_line[index] -- derived from where
        the cursor is, since the line may wrap over several rows."""
        cols = self.buffer.cols
        linear = self.buffer.cursor_row * cols + self.buffer.cursor_col + (index - self.line_cursor)
        return linear % cols, linear // cols

    def _redraw_line(self) -> None:
        """Rewrites current_line in place, the selected part inverted."""
        selection = self.selection or (len(self.current_line), len(self.current_line))
        pieces = ((0, selection[0], False), (selection[0], selection[1], True),
                  (selection[1], len(self.current_line), False))
        for start, end, inverted in pieces:
            if start >= end:
                continue
            col, row = self._position_of(start)
            if row < 0:
                continue  # scrolled off the top
            text = self._display(self.current_line[start:end])
            if inverted:
                self.buffer.write_string(col, row, text, fg=self.buffer.default_bg, bg=self.buffer.default_fg)
            else:
                self.buffer.write_string(col, row, text)
        self._sync_cursor()

    def _clear_selection(self) -> None:
        """Drops the selection, un-inverting it on screen."""
        had_selection = self.selection is not None
        self.selection_anchor = None
        if had_selection:
            self._redraw_line()

    def _delete_selection(self) -> bool:
        """Removes the selected text (cursor ends up where it began).
        Returns whether there was anything to remove."""
        selection = self.selection
        self.selection_anchor = None
        if selection is None:
            return False
        start, end = selection
        self._adjust_cursor(start - self.line_cursor)
        self.current_line = self.current_line[:start] + self.current_line[end:]
        tail = self.current_line[start:]
        self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row,
                                 string=self._display(tail) + " " * (end - start))
        self._sync_cursor()
        return True

    def _handle_motion_select(self, motion: int) -> None:
        """A cursor motion with Shift held: moves the cursor like
        _handle_motion, but extends the selection from where it started."""
        if motion not in _CURSOR_MOTIONS:
            return
        if self.selection_anchor is None:
            self.selection_anchor = self.line_cursor
        self._move_cursor(motion)
        self._redraw_line()

    def select_all(self) -> None:
        self.selection_anchor = 0
        self._adjust_cursor(len(self.current_line) - self.line_cursor)
        self._redraw_line()

    def copy(self) -> None:
        """Puts the selection on the clipboard -- never a masked (password) one."""
        if self.masked or self.selection is None:
            return
        self.clipboard.set_text(self.selected_text)

    def cut(self) -> None:
        if self.masked or self.selection is None:
            return
        self.copy()
        self._delete_selection()

    def paste(self) -> None:
        """Types the clipboard's text in, replacing the selection -- line
        breaks become spaces, so pasting never submits a line by itself."""
        text = " ".join(self.clipboard.get_text().splitlines())
        if text:
            self._handle_text(text)

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

    def _current_word_start(self) -> int:
        """Index in current_line where the word ending at line_cursor begins
        (the character right after the nearest preceding space, or 0)."""
        return self.current_line.rfind(" ", 0, self.line_cursor) + 1

    def _handle_tab(self) -> None:
        """Completes the word at the cursor against self._complete's candidates.
        One candidate: completes it outright. Multiple candidates: the first
        Tab inserts the first match, a second consecutive Tab (nothing else
        typed in between) prints the full candidate list without changing the
        line -- like bash's double-Tab -- and every Tab after that cycles to
        the next candidate, wrapping around."""
        if self._complete is None or self.masked:
            return

        word_start = self._current_word_start()
        current_word = self.current_line[word_start:self.line_cursor]

        continuing = (
            self._tab_word_start == word_start
            and bool(self._tab_candidates)
            and current_word == self._tab_candidates[self._tab_index]
        )

        if continuing:
            self._tab_press_count += 1
        else:
            self._tab_word_start = word_start
            self._tab_candidates = sorted(self._complete(current_word))
            self._tab_index = 0
            self._tab_press_count = 1

        if not self._tab_candidates:
            return

        if len(self._tab_candidates) == 1:
            self._replace_current_word(word_start, self._tab_candidates[0])
            self._tab_candidates = []  # nothing left to cycle through
            return

        if continuing and self._tab_press_count == 2:
            self._show_completion_list(self._tab_candidates)
            return

        if continuing:
            self._tab_index = (self._tab_index + 1) % len(self._tab_candidates)
        self._replace_current_word(word_start, self._tab_candidates[self._tab_index])

    def _replace_current_word(self, word_start: int, replacement: str) -> None:
        """Replaces current_line[word_start:line_cursor] with `replacement`,
        reusing the same backspace/type paths as regular editing so the
        screen, current_line and cursor all stay in sync automatically."""
        for _ in range(self.line_cursor - word_start):
            self._handle_motion(pyglet.window.key.MOTION_BACKSPACE)
        self._handle_text(replacement)

    def _reprint_current_line(self) -> None:
        """Redraws the prompt and current_line on a fresh row, preserving
        line_cursor -- unlike start_line(), which resets current_line for a
        brand new input. Used after printing a completion list mid-edit."""
        self._advance_row(1)
        self.buffer.cursor_col = 0
        prompt = self._get_prompt() if self._get_prompt is not None else ""
        if prompt:
            self.buffer.write_string(col=0, row=self.buffer.cursor_row, string=prompt)
        self.buffer.cursor_col = len(prompt)
        if self.current_line:
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=self._display(self.current_line))
        target = self.line_cursor
        self.line_cursor = 0
        self._adjust_cursor(target)

    def _show_completion_list(self, candidates: list[str]) -> None:
        self._advance_row(1)
        self.buffer.write_string(col=0, row=self.buffer.cursor_row, string="  ".join(candidates))
        self._reprint_current_line()

    def _handle_text(self, text: str):
        """Handles simple text input key presses, not correlating to any pyglet models."""
        if text is None:
            return
        text = "".join(char for char in text if char.isprintable())
        if not text:
            return
        self._delete_selection()  # typing replaces whatever is selected
        if self.insert_mode:
            end = self.line_cursor + len(text)
            self.current_line = self.current_line[:self.line_cursor] + text + self.current_line[end:]
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=self._display(text))
            self._adjust_cursor(len(text))
        else:
            tail = self.current_line[self.line_cursor:]
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=self._display(text + tail))
            self.current_line = self.current_line[:self.line_cursor] + text + tail
            self._adjust_cursor(len(text))

    def _handle_motion(self, motion: int):
        """Handles key presses pyglet models as a text motion: Backspace, Left, Right, End..."""
        logger.debug(f"INPUT: Motion='{motion}'")
        if motion in _CURSOR_MOTIONS:
            self._clear_selection()  # moving without Shift drops the selection
            self._move_cursor(motion)
            return

        match motion:
            case None:
                return

            case pyglet.window.key.MOTION_BACKSPACE:
                if self._delete_selection():
                    return
                if self.line_cursor == 0:
                    return
                tail = self.current_line[self.line_cursor:]
                self.current_line = self.current_line[:self.line_cursor - 1] + tail
                self._adjust_cursor(-1)
                self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=self._display(tail) + " ")

            case pyglet.window.key.MOTION_UP:
                entry = self.history.previous(self.current_line)
                if entry is not None:
                    self._clear_selection()
                    self._replace_current_line(entry)

            case pyglet.window.key.MOTION_DOWN:
                entry = self.history.next()
                if entry is not None:
                    self._clear_selection()
                    self._replace_current_line(entry)

            case pyglet.window.key.MOTION_PREVIOUS_PAGE:  # Page Up: look further back into scrollback history
                self.buffer.scroll_view(self.buffer.rows // 2)

            case pyglet.window.key.MOTION_NEXT_PAGE:  # Page Down: move back toward the live view
                self.buffer.scroll_view(-(self.buffer.rows // 2))

    def _move_cursor(self, motion: int) -> None:
        """Moves the cursor within the line for one of _CURSOR_MOTIONS --
        shared by plain motions and Shift-selecting ones."""
        match motion:
            case pyglet.window.key.MOTION_LEFT:
                if self.line_cursor > 0:
                    self._adjust_cursor(-1)

            case pyglet.window.key.MOTION_RIGHT:
                if self.line_cursor < len(self.current_line):
                    self._adjust_cursor(1)

            case pyglet.window.key.MOTION_BEGINNING_OF_LINE:
                self._adjust_cursor(-self.line_cursor)
                self.line_cursor = 0

            case pyglet.window.key.MOTION_END_OF_LINE:
                self._adjust_cursor(len(self.current_line) - self.line_cursor)
                self.line_cursor = len(self.current_line)

            case pyglet.window.key.MOTION_NEXT_WORD:
                self._adjust_cursor(self._next_word_boundary() - self.line_cursor)

            case pyglet.window.key.MOTION_PREVIOUS_WORD:
                self._adjust_cursor(self._previous_word_boundary() - self.line_cursor)

    def _handle_key(self, symbol: int, modifiers: int) -> None:
        """Handles key presses pyglet doesn't model as a text motion: Insert, Delete..."""
        logger.debug(f"INPUT: Symbol='{symbol}', modifiers='{modifiers}'")
        ctrl_held = bool(modifiers & pyglet.window.key.MOD_CTRL)

        if ctrl_held and symbol == key.C:
            self.copy()

        elif ctrl_held and symbol == key.X:
            self.cut()

        elif ctrl_held and symbol == key.V:
            self.paste()

        elif ctrl_held and symbol == key.A:
            self.select_all()

        elif symbol == pyglet.window.key.INSERT:
            self.insert_mode = not self.insert_mode
            self._sync_cursor()

        # With a selection, Delete / Ctrl+Backspace just remove it. Plain
        # Backspace isn't handled here: pyglet also sends it as a text motion
        # (right after this key press), and _handle_motion removes it there --
        # doing it in both places would delete one character too many.
        elif (symbol == pyglet.window.key.DELETE or (symbol == pyglet.window.key.BACKSPACE and ctrl_held)) \
                and self._delete_selection():
            return

        elif symbol == pyglet.window.key.DELETE and ctrl_held:
            end = self._next_word_boundary()
            if end == self.line_cursor:
                return
            deleted = end - self.line_cursor
            tail = self.current_line[end:]
            self.current_line = self.current_line[:self.line_cursor] + tail
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=self._display(tail) + " " * deleted)

        elif symbol == pyglet.window.key.DELETE:
            if self.line_cursor >= len(self.current_line):
                return
            tail = self.current_line[1 + self.line_cursor:]
            self.current_line = self.current_line[:self.line_cursor] + tail
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=self._display(tail) + " ")

        elif symbol == pyglet.window.key.BACKSPACE and ctrl_held:
            start = self._previous_word_boundary()
            if start == self.line_cursor:
                return
            deleted = self.line_cursor - start
            tail = self.current_line[self.line_cursor:]
            self.current_line = self.current_line[:start] + tail
            self._adjust_cursor(start - self.line_cursor)
            self.buffer.write_string(col=self.buffer.cursor_col, row=self.buffer.cursor_row, string=self._display(tail) + " " * deleted)
        
        elif symbol == pyglet.window.key.UP and ctrl_held:
            self.buffer.scroll_view(1)

        elif symbol == pyglet.window.key.DOWN and ctrl_held:
            self.buffer.scroll_view(-1)

        elif symbol == pyglet.window.key.TAB:
            self._clear_selection()
            self._handle_tab()

    def _handle_enter(self):
        """Handles enter key presses. Leaves writing the prompt for the next line to
        start_line() -- see its docstring for why that's the caller's decision."""
        logger.debug(f"INPUT: 'enter', Current Line='{self.current_line}")
        self._clear_selection()  # the submitted line stays on screen -- not highlighted
        self._advance_row(1)
        self.buffer.cursor_col = 0
        self._sync_cursor()

        line = self.current_line
        self.current_line = ""
        self.line_cursor = 0

        if self._pending_submit is not None:
            callback = self._pending_submit
            self._pending_submit = None
            self.masked = False
            self._sync_cursor()
            callback(line)
            return

        if line.strip():
            self.history.add(line)

        if self._on_submit is not None:
            self._on_submit(line)

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

    def request_line(self, callback: Callable[[str], None], masked: bool = False) -> None:
        """Redirects the next submitted line to callback instead of the normal
        kernel dispatch -- used for interactive prompts like password entry."""
        self._pending_submit = callback
        self.masked = masked

    def _display(self, text: str) -> str:
        """What gets drawn on screen for a piece of current_line content --
        asterisks while masked, the real text otherwise."""
        return "*" * len(text) if self.masked else text