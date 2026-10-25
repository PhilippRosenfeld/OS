from unittest.mock import patch

import pyglet
import pytest

from horus.apps.shell_window import ShellWindow
from horus.apps.window_manager import show_window
from horus.display.screen_buffer import ScreenBuffer
from horus.session.context import Context
from horus.session.history import CommandHistory
from horus.shell.clipboard import Clipboard, SystemClipboard
from horus.shell.input_handler import InputHandler
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.shell_screen import ShellScreen

key = pyglet.window.key
CTRL = key.MOD_CTRL


def row_text(buffer, row):
    return "".join(buffer.get_cell(c, row).char for c in range(buffer.cols))


def make_input(text="hello world", clipboard=None, cols=40):
    buffer = ScreenBuffer(cols, 5)
    submitted = []
    handler = InputHandler(buffer, CommandHistory(), on_submit=submitted.append, get_prompt=lambda: "> ",
                           clipboard=clipboard)
    handler._handle_text(text)
    return handler, buffer, submitted


def shift(handler, motion, times=1):
    for _ in range(times):
        handler._handle_motion_select(motion)


def inverted(buffer, col, row=0):
    cell = buffer.get_cell(col, row)
    return cell.fg_color == buffer.default_bg and cell.bg_color == buffer.default_fg


# --- selecting ---

def test_shift_left_selects_backwards_from_the_cursor():
    handler, buffer, _ = make_input()
    shift(handler, key.MOTION_LEFT, 5)
    assert handler.selection == (6, 11) and handler.selected_text == "world"


def test_the_selection_is_shown_inverted_and_nothing_else_is():
    handler, buffer, _ = make_input()
    shift(handler, key.MOTION_LEFT, 5)
    assert all(inverted(buffer, 2 + i) for i in range(6, 11))    # "world", after the 2-char prompt
    assert not any(inverted(buffer, 2 + i) for i in range(0, 6))


def test_shift_home_end_and_word_motions_select_too():
    handler, _, _ = make_input()
    shift(handler, key.MOTION_BEGINNING_OF_LINE)
    assert handler.selected_text == "hello world"
    handler._handle_motion(key.MOTION_END_OF_LINE)
    shift(handler, key.MOTION_PREVIOUS_WORD)
    assert handler.selected_text == "world"


def test_shifting_back_to_the_anchor_selects_nothing():
    handler, _, _ = make_input()
    shift(handler, key.MOTION_LEFT, 2)
    shift(handler, key.MOTION_RIGHT, 2)
    assert handler.selection is None


def test_moving_without_shift_drops_the_selection_and_its_highlight():
    handler, buffer, _ = make_input()
    shift(handler, key.MOTION_LEFT, 5)
    handler._handle_motion(key.MOTION_LEFT)
    assert handler.selection is None
    assert not any(inverted(buffer, c) for c in range(buffer.cols))


def test_ctrl_a_selects_the_whole_line():
    handler, _, _ = make_input()
    handler._handle_motion(key.MOTION_BEGINNING_OF_LINE)
    handler._handle_key(key.A, CTRL)
    assert handler.selected_text == "hello world" and handler.line_cursor == 11


# --- editing a selection ---

def test_typing_replaces_the_selection():
    handler, buffer, _ = make_input()
    shift(handler, key.MOTION_LEFT, 5)
    handler._handle_text("there")
    assert handler.current_line == "hello there"
    assert row_text(buffer, 0).rstrip() == "> hello there"
    assert not any(inverted(buffer, c) for c in range(buffer.cols))


def test_backspace_removes_just_the_selection():
    """pyglet sends Backspace as a key press *and* a text motion -- the
    selection must go, but not one character more."""
    handler, buffer, _ = make_input()
    shift(handler, key.MOTION_LEFT, 5)
    handler._handle_key(key.BACKSPACE, 0)
    handler._handle_motion(key.MOTION_BACKSPACE)
    assert handler.current_line == "hello "
    assert row_text(buffer, 0).rstrip() == "> hello"


def test_delete_removes_just_the_selection():
    handler, buffer, _ = make_input()
    handler._handle_motion(key.MOTION_BEGINNING_OF_LINE)
    shift(handler, key.MOTION_RIGHT, 6)
    handler._handle_key(key.DELETE, 0)
    handler._handle_motion(key.MOTION_DELETE)
    assert handler.current_line == "world"
    assert row_text(buffer, 0).rstrip() == "> world"


def test_ctrl_backspace_removes_just_the_selection():
    handler, _, _ = make_input()
    shift(handler, key.MOTION_LEFT, 3)
    handler._handle_key(key.BACKSPACE, CTRL)
    assert handler.current_line == "hello wo"


def test_enter_submits_the_whole_line_and_unhighlights_it():
    handler, buffer, submitted = make_input()
    shift(handler, key.MOTION_LEFT, 5)
    handler._handle_enter()
    assert submitted == ["hello world"]
    assert not any(inverted(buffer, c) for c in range(buffer.cols))


# --- copy / cut / paste ---

def test_ctrl_c_copies_the_selection():
    handler, _, _ = make_input()
    shift(handler, key.MOTION_LEFT, 5)
    handler._handle_key(key.C, CTRL)
    assert handler.clipboard.get_text() == "world"
    assert handler.current_line == "hello world"


def test_ctrl_c_without_a_selection_leaves_the_clipboard_alone():
    clipboard = Clipboard()
    clipboard.set_text("before")
    handler, _, _ = make_input(clipboard=clipboard)
    handler._handle_key(key.C, CTRL)
    assert clipboard.get_text() == "before"


def test_ctrl_x_cuts_the_selection():
    handler, _, _ = make_input()
    shift(handler, key.MOTION_LEFT, 6)
    handler._handle_key(key.X, CTRL)
    assert handler.clipboard.get_text() == " world" and handler.current_line == "hello"


def test_ctrl_v_pastes_at_the_cursor():
    clipboard = Clipboard()
    clipboard.set_text(" again")
    handler, buffer, _ = make_input(clipboard=clipboard)
    handler._handle_key(key.V, CTRL)
    assert handler.current_line == "hello world again"
    assert row_text(buffer, 0).rstrip() == "> hello world again"


def test_ctrl_v_replaces_the_selection():
    clipboard = Clipboard()
    clipboard.set_text("there")
    handler, _, _ = make_input(clipboard=clipboard)
    shift(handler, key.MOTION_LEFT, 5)
    handler._handle_key(key.V, CTRL)
    assert handler.current_line == "hello there"


def test_pasting_several_lines_joins_them_instead_of_submitting():
    clipboard = Clipboard()
    clipboard.set_text("ls\r\ncd /tmp\n")
    handler, _, submitted = make_input("", clipboard=clipboard)
    handler._handle_key(key.V, CTRL)
    assert handler.current_line == "ls cd /tmp" and submitted == []


def test_cut_copy_paste_round_trip():
    handler, _, _ = make_input()
    handler._handle_motion(key.MOTION_BEGINNING_OF_LINE)
    shift(handler, key.MOTION_NEXT_WORD)                  # "hello "
    handler._handle_key(key.X, CTRL)
    handler._handle_motion(key.MOTION_END_OF_LINE)
    handler._handle_text(" ")
    handler._handle_key(key.V, CTRL)
    assert handler.current_line == "world hello "


# --- masked input (passwords) ---

def test_a_masked_selection_is_never_copied():
    clipboard = Clipboard()
    handler, _, _ = make_input("", clipboard=clipboard)
    handler.request_line(lambda line: None, masked=True)
    handler._handle_text("secret")
    handler._handle_key(key.A, CTRL)
    handler._handle_key(key.C, CTRL)
    handler._handle_key(key.X, CTRL)
    assert clipboard.get_text() == ""
    assert handler.current_line == "secret"


def test_deleting_in_masked_input_keeps_the_real_characters():
    """Regression: Delete used to write the on-screen '*' into the line itself."""
    entered = []
    handler, buffer, _ = make_input("")
    handler.request_line(entered.append, masked=True)
    handler._handle_text("abcd")
    handler._handle_motion(key.MOTION_BEGINNING_OF_LINE)
    handler._handle_key(key.DELETE, 0)
    handler._handle_enter()
    assert entered == ["bcd"]


# --- clipboards ---

class FakePygletWindow:
    def __init__(self, fail=False):
        self.text = ""
        self.fail = fail

    def get_clipboard_text(self):
        if self.fail:
            raise RuntimeError("no clipboard")
        return self.text

    def set_clipboard_text(self, text):
        if self.fail:
            raise RuntimeError("no clipboard")
        self.text = text


def test_system_clipboard_goes_through_the_os_window():
    window = FakePygletWindow()
    clipboard = SystemClipboard(window)
    clipboard.set_text("copied")
    assert window.text == "copied"
    window.text = "from another program"
    assert clipboard.get_text() == "from another program"


def test_system_clipboard_falls_back_to_memory_when_the_os_refuses():
    clipboard = SystemClipboard(FakePygletWindow(fail=True))
    clipboard.set_text("kept")
    assert clipboard.get_text() == "kept"


# --- wiring: screens and windows ---

def test_shift_motions_reach_the_shell_through_the_screen_manager():
    handler, buffer, _ = make_input("")
    screens = ScreenManager()
    screens.push(ShellScreen(handler, screens))
    screens.handle_text("hello world")
    screens.handle_motion_select(key.MOTION_LEFT)
    assert handler.selected_text == "d"


def test_copy_in_a_window_pastes_in_the_main_shell():
    with patch("pyglet.clock.schedule_interval"), patch("pyglet.clock.unschedule"):
        clipboard = Clipboard()
        main, buffer, _ = make_input("", clipboard=clipboard, cols=80)
        screens = ScreenManager()
        ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, screens=screens, clipboard=clipboard)
        screens.push(ShellScreen(main, screens))
        window = ShellWindow(ctx, "App")
        manager = show_window(ctx, window)

        manager.handle_text("from window")
        manager.handle_motion_select(key.MOTION_PREVIOUS_WORD)
        manager.handle_key(key.C, CTRL)
        manager.handle_key(key.LALT, key.MOD_CTRL)        # Ctrl+Alt: focus the shell
        manager.handle_key(key.V, CTRL)
    assert main.current_line == "window"


@pytest.mark.parametrize("motion", [key.MOTION_UP, key.MOTION_BACKSPACE])
def test_shift_with_non_cursor_motions_does_nothing(motion):
    handler, _, _ = make_input()
    shift(handler, motion)
    assert handler.selection is None and handler.current_line == "hello world"
