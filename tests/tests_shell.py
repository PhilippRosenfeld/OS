import pyglet
import pytest

from horus.display.screen_buffer import ScreenBuffer
from horus.shell.input_handler import InputHandler

key = pyglet.window.key


def make(cols=20, rows=5):
    buffer = ScreenBuffer(cols, rows)
    handler = InputHandler(buffer)
    return handler, buffer


def row_text(buffer, row):
    return "".join(buffer.get_cell(c, row).char for c in range(buffer.cols))


# --- basic text entry ---

def test_initial_state_syncs_cursor_onto_buffer():
    handler, buffer = make()
    assert buffer.cursor_visible is True
    assert buffer.cursor_block is False  # insert_mode starts False -> thin bar


def test_handle_text_writes_and_advances_cursor():
    handler, buffer = make()
    handler._handle_text("abc")
    assert handler.current_line == "abc"
    assert handler.line_cursor == 3
    assert buffer.cursor_col == 3
    assert row_text(buffer, 0).startswith("abc")


def test_handle_text_ignores_non_printable_characters():
    handler, buffer = make()
    handler._handle_text("a\r\n\tb")
    assert handler.current_line == "ab"


def test_handle_text_ignores_none_and_empty():
    handler, buffer = make()
    handler._handle_text(None)
    handler._handle_text("")
    assert handler.current_line == ""


def test_handle_text_wraps_to_next_row():
    handler, buffer = make(cols=5, rows=3)
    handler._handle_text("ABCDEFG")
    assert row_text(buffer, 0) == "ABCDE"
    assert row_text(buffer, 1).startswith("FG")
    assert buffer.cursor_row == 1
    assert buffer.cursor_col == 2


def test_default_mode_inserts_and_pushes_tail_right():
    handler, buffer = make()
    handler._handle_text("ACE")
    for _ in range(2):
        handler._handle_motion(key.MOTION_LEFT)  # line_cursor: 3 -> 1, keeps buffer.cursor_col in sync
    handler._handle_text("B")
    assert handler.current_line == "ABCE"
    assert row_text(buffer, 0).startswith("ABCE")


def test_insert_mode_overwrites_without_pushing():
    handler, buffer = make()
    handler._handle_text("ABCDE")
    handler._handle_key(key.INSERT, 0)
    assert handler.insert_mode is True
    assert buffer.cursor_block is True
    for _ in range(4):
        handler._handle_motion(key.MOTION_LEFT)  # line_cursor: 5 -> 1
    handler._handle_text("X")
    assert handler.current_line == "AXCDE"
    assert row_text(buffer, 0).startswith("AXCDE")


# --- backspace / delete ---

def test_backspace_removes_previous_character_and_shifts_tail():
    handler, buffer = make()
    handler._handle_text("ABCDE")
    for _ in range(2):
        handler._handle_motion(key.MOTION_LEFT)  # line_cursor: 5 -> 3
    handler._handle_motion(key.MOTION_BACKSPACE)
    assert handler.current_line == "ABDE"
    assert row_text(buffer, 0).startswith("ABDE")


def test_backspace_at_start_of_line_is_a_no_op():
    handler, buffer = make()
    handler._handle_text("abc")
    handler.line_cursor = 0
    handler._handle_motion(key.MOTION_BACKSPACE)
    assert handler.current_line == "abc"


def test_delete_removes_character_at_cursor():
    handler, buffer = make()
    handler._handle_text("ABCDE")
    for _ in range(4):
        handler._handle_motion(key.MOTION_LEFT)  # line_cursor: 5 -> 1
    handler._handle_key(key.DELETE, 0)
    assert handler.current_line == "ACDE"
    assert row_text(buffer, 0).startswith("ACDE")


def test_delete_at_end_of_line_is_a_no_op():
    handler, buffer = make()
    handler._handle_text("abc")
    handler._handle_key(key.DELETE, 0)
    assert handler.current_line == "abc"


def test_ctrl_backspace_deletes_whole_previous_word():
    handler, buffer = make()
    handler._handle_text("hello world")
    handler._handle_key(key.BACKSPACE, key.MOD_CTRL)
    assert handler.current_line == "hello "
    assert handler.line_cursor == 6


def test_ctrl_delete_deletes_whole_next_word():
    handler, buffer = make()
    handler._handle_text("hello world")
    handler._handle_motion(key.MOTION_BEGINNING_OF_LINE)
    handler._handle_key(key.DELETE, key.MOD_CTRL)
    assert handler.current_line == "world"
    assert handler.line_cursor == 0
    assert row_text(buffer, 0).startswith("world")


# --- cursor motion ---

def test_left_right_motion_moves_line_cursor():
    handler, buffer = make()
    handler._handle_text("abc")
    handler._handle_motion(key.MOTION_LEFT)
    assert handler.line_cursor == 2
    handler._handle_motion(key.MOTION_RIGHT)
    assert handler.line_cursor == 3


def test_right_motion_stops_at_end_of_line():
    handler, buffer = make()
    handler._handle_text("ab")
    handler._handle_motion(key.MOTION_RIGHT)
    assert handler.line_cursor == 2


def test_left_motion_stops_at_start_of_line():
    handler, buffer = make()
    handler._handle_text("ab")
    handler.line_cursor = 0
    handler._handle_motion(key.MOTION_LEFT)
    assert handler.line_cursor == 0


def test_beginning_and_end_of_line_motions():
    handler, buffer = make()
    handler._handle_text("hello")
    handler._handle_motion(key.MOTION_BEGINNING_OF_LINE)
    assert handler.line_cursor == 0
    assert buffer.cursor_col == 0
    handler._handle_motion(key.MOTION_END_OF_LINE)
    assert handler.line_cursor == 5
    assert buffer.cursor_col == 5


@pytest.mark.parametrize("line,pos,expected", [
    ("hello world", 0, 6),
    ("hello world", 6, 11),
    ("hello   world", 5, 8),
    ("helloworld", 0, 10),
    ("", 0, 0),
])
def test_next_word_boundary(line, pos, expected):
    handler, buffer = make(cols=40)
    handler._handle_text(line)
    handler.line_cursor = pos
    assert handler._next_word_boundary() == expected


@pytest.mark.parametrize("line,pos,expected", [
    ("hello world", 11, 6),
    ("hello world", 6, 0),
    ("hello   world", 6, 0),
    ("hello world", 0, 0),
    ("", 0, 0),
])
def test_previous_word_boundary(line, pos, expected):
    handler, buffer = make(cols=40)
    handler._handle_text(line)
    handler.line_cursor = pos
    assert handler._previous_word_boundary() == expected


# --- insert toggle ---

def test_insert_key_toggles_mode_and_cursor_style():
    handler, buffer = make()
    assert handler.insert_mode is False
    handler._handle_key(key.INSERT, 0)
    assert handler.insert_mode is True
    assert buffer.cursor_block is True
    handler._handle_key(key.INSERT, 0)
    assert handler.insert_mode is False
    assert buffer.cursor_block is False


# --- page up/down (scrollback view) ---

def test_page_up_down_move_view_offset():
    handler, buffer = make(cols=10, rows=4)
    for i in range(10):
        handler._handle_text(f"line{i}")
        handler._handle_enter()
    assert buffer.view_offset == 0
    handler._handle_motion(key.MOTION_PREVIOUS_PAGE)
    assert buffer.view_offset > 0
    handler._handle_motion(key.MOTION_NEXT_PAGE)
    assert buffer.view_offset == 0


# --- enter / submit ---

def test_enter_calls_on_submit_with_current_line_and_resets_it():
    submitted = []
    buffer = ScreenBuffer(20, 5)
    handler = InputHandler(buffer, on_submit=submitted.append)
    handler._handle_text("hello")
    handler._handle_enter()
    assert submitted == ["hello"]
    assert handler.current_line == ""
    assert handler.line_cursor == 0


def test_enter_advances_cursor_before_submit_so_output_lands_below():
    seen_rows = []
    buffer = ScreenBuffer(20, 5)

    def on_submit(line):
        seen_rows.append(buffer.cursor_row)

    handler = InputHandler(buffer, on_submit=on_submit)
    handler._handle_text("cmd")
    row_before_enter = buffer.cursor_row
    handler._handle_enter()
    assert seen_rows[0] == row_before_enter + 1


def test_enter_without_submit_callback_does_not_raise():
    buffer = ScreenBuffer(20, 5)
    handler = InputHandler(buffer)
    handler._handle_text("hi")
    handler._handle_enter()  # should not raise
    assert handler.current_line == ""
