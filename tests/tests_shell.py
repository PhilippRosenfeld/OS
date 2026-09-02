import pyglet
import pytest

from horus.display.screen_buffer import ScreenBuffer
from horus.session.history import CommandHistory
from horus.shell.input_handler import InputHandler

key = pyglet.window.key


def make(cols=20, rows=5):
    buffer = ScreenBuffer(cols, rows)
    history = CommandHistory()
    handler = InputHandler(buffer, history)
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
    history = CommandHistory()
    handler = InputHandler(buffer, history, on_submit=submitted.append)
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

    history = CommandHistory()
    handler = InputHandler(buffer, history, on_submit=on_submit)
    handler._handle_text("cmd")
    row_before_enter = buffer.cursor_row
    handler._handle_enter()
    assert seen_rows[0] == row_before_enter + 1


def test_enter_without_submit_callback_does_not_raise():
    buffer = ScreenBuffer(20, 5)
    history = CommandHistory()
    handler = InputHandler(buffer, history)
    handler._handle_text("hi")
    handler._handle_enter()  # should not raise
    assert handler.current_line == ""


# --- prompt ---

def test_no_prompt_by_default_input_starts_at_column_zero():
    handler, buffer = make()
    assert buffer.cursor_col == 0
    assert row_text(buffer, 0).strip() == ""


def test_get_prompt_is_written_at_construction_and_offsets_the_cursor():
    buffer = ScreenBuffer(20, 5)
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: "root@/home > ")
    assert row_text(buffer, 0).startswith("root@/home > ")
    assert buffer.cursor_col == len("root@/home > ")
    assert handler.line_cursor == 0


def test_typed_text_lands_after_the_prompt():
    buffer = ScreenBuffer(20, 5)
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: "> ")
    handler._handle_text("ls")
    assert row_text(buffer, 0).startswith("> ls")
    assert handler.current_line == "ls"  # the prompt itself is never part of current_line


def test_prompt_reflects_the_callback_live_e_g_after_cd():
    state = {"cwd": "/home"}
    buffer = ScreenBuffer(30, 5)
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: f"root@{state['cwd']} > ")
    state["cwd"] = "/etc"
    handler.start_line()
    assert row_text(buffer, 0).startswith("root@/etc > ")


def test_start_line_after_enter_draws_prompt_on_the_new_row():
    buffer = ScreenBuffer(20, 5)
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: "> ")
    handler._handle_text("cmd")
    handler._handle_enter()
    handler.start_line()
    assert row_text(buffer, 1).startswith("> ")
    assert buffer.cursor_row == 1
    assert buffer.cursor_col == len("> ")


def test_backspace_and_home_cannot_reach_into_the_prompt():
    buffer = ScreenBuffer(20, 5)
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: "> ")
    handler._handle_text("x")
    handler._handle_motion(key.MOTION_BACKSPACE)
    handler._handle_motion(key.MOTION_BACKSPACE)  # already empty, must be a no-op
    assert buffer.cursor_col == len("> ")
    assert row_text(buffer, 0) == "> " + " " * 18
    handler._handle_text("ab")
    handler._handle_motion(key.MOTION_BEGINNING_OF_LINE)
    assert buffer.cursor_col == len("> ")


# --- Tab completion ---

def make_completing(files, cols=60, rows=10):
    buffer = ScreenBuffer(cols, rows)
    history = CommandHistory()
    handler = InputHandler(buffer, history, complete=lambda prefix: [f for f in files if f.startswith(prefix)])
    return handler, buffer


def test_tab_completes_a_single_match_outright():
    handler, buffer = make_completing(["poem.txt", "readme.txt"])
    handler._handle_text("cat p")
    handler._handle_key(key.TAB, 0)
    assert handler.current_line == "cat poem.txt"
    assert handler.line_cursor == len("cat poem.txt")


def test_tab_completes_the_first_word_too():
    handler, buffer = make_completing(["poem.txt"])
    handler._handle_text("po")
    handler._handle_key(key.TAB, 0)
    assert handler.current_line == "poem.txt"


def test_tab_with_multiple_matches_inserts_the_first_one_alphabetically():
    handler, buffer = make_completing(["avocado.txt", "apple.txt", "alpha.txt"])
    handler._handle_text("cat a")
    handler._handle_key(key.TAB, 0)
    assert handler.current_line == "cat alpha.txt"


def test_second_tab_shows_the_full_list_without_changing_the_line():
    handler, buffer = make_completing(["avocado.txt", "apple.txt", "alpha.txt"])
    handler._handle_text("cat a")
    handler._handle_key(key.TAB, 0)  # 1st: completes to "cat alpha.txt"
    handler._handle_key(key.TAB, 0)  # 2nd: shows the list instead of cycling

    assert handler.current_line == "cat alpha.txt"  # untouched by the listing
    listing = row_text(buffer, 1).rstrip()
    assert "alpha.txt" in listing and "apple.txt" in listing and "avocado.txt" in listing
    assert row_text(buffer, 2).rstrip() == "cat alpha.txt"  # line reprinted below the list
    assert buffer.cursor_row == 2


def test_third_and_further_tabs_cycle_through_candidates():
    handler, buffer = make_completing(["avocado.txt", "apple.txt", "alpha.txt"])
    handler._handle_text("cat a")
    handler._handle_key(key.TAB, 0)  # 1st -> alpha.txt
    handler._handle_key(key.TAB, 0)  # 2nd -> shows list, line unchanged
    handler._handle_key(key.TAB, 0)  # 3rd -> cycle to apple.txt
    assert handler.current_line == "cat apple.txt"
    handler._handle_key(key.TAB, 0)  # 4th -> cycle to avocado.txt
    assert handler.current_line == "cat avocado.txt"
    handler._handle_key(key.TAB, 0)  # 5th -> wraps back to alpha.txt
    assert handler.current_line == "cat alpha.txt"


def test_tab_with_no_matches_is_a_noop():
    handler, buffer = make_completing(["poem.txt"])
    handler._handle_text("cat zzz")
    handler._handle_key(key.TAB, 0)
    assert handler.current_line == "cat zzz"


def test_typing_between_tabs_starts_a_fresh_completion():
    handler, buffer = make_completing(["alpha.txt", "apple.txt"])
    handler._handle_text("cat a")
    handler._handle_key(key.TAB, 0)  # -> "cat alpha.txt"
    handler._handle_text("!")  # something else typed -> breaks the cycling streak
    handler._handle_key(key.TAB, 0)  # fresh completion for "alpha.txt!" -> no matches
    assert handler.current_line == "cat alpha.txt!"


def test_tab_without_a_completer_does_not_raise():
    handler, buffer = make()
    handler._handle_text("cat p")
    handler._handle_key(key.TAB, 0)  # complete=None -> should not raise
    assert handler.current_line == "cat p"


def test_tab_is_disabled_while_masked():
    handler, buffer = make_completing(["poem.txt"])
    handler.masked = True
    handler._handle_text("p")
    handler._handle_key(key.TAB, 0)
    assert handler.current_line == "p"
