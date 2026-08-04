import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen_manager import ScreenManager
from horus.ui.shell_screen import ShellScreen
from horus.ui.menu_screen import MenuScreen, MenuOption
from horus.shell.input_handler import InputHandler

key = pyglet.window.key


def row_text(buffer, row):
    return "".join(buffer.get_cell(c, row).char for c in range(buffer.cols)).rstrip()


# --- ScreenManager ---

def test_screen_manager_starts_with_no_active_screen():
    manager = ScreenManager()
    assert manager.active is None


def test_screen_manager_push_makes_screen_active_and_calls_on_push():
    manager = ScreenManager()
    events = []
    screen = MenuScreen(ScreenBuffer(20, 5), "T", [MenuOption("A", lambda: None)], manager)
    manager.push(screen)
    assert manager.active is screen


def test_screen_manager_pop_restores_previous_screen():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    handler = InputHandler(buffer)
    shell = ShellScreen(handler)
    manager.push(shell)
    menu = MenuScreen(buffer, "T", [MenuOption("A", lambda: None)], manager)
    manager.push(menu)
    assert manager.active is menu
    manager.pop()
    assert manager.active is shell


def test_screen_manager_pop_on_empty_stack_is_a_no_op():
    manager = ScreenManager()
    manager.pop()  # should not raise
    assert manager.active is None


def test_screen_manager_only_forwards_to_top_screen():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    handler = InputHandler(buffer)
    manager.push(ShellScreen(handler))
    manager.handle_text("hi")
    assert handler.current_line == "hi"

    menu = MenuScreen(buffer, "T", [MenuOption("A", lambda: None)], manager)
    manager.push(menu)
    manager.handle_text("more")  # MenuScreen ignores text; must NOT reach the shell underneath
    assert handler.current_line == "hi"


# --- MenuScreen ---

def make_menu(cols=30, rows=10, labels=("Resume", "Settings", "Quit")):
    buffer = ScreenBuffer(cols, rows)
    manager = ScreenManager()
    selections = []
    options = [MenuOption(label, (lambda l=label: selections.append(l))) for label in labels]
    menu = MenuScreen(buffer, "Horus Menu", options, manager)
    manager.push(menu)
    return menu, buffer, manager, selections


def test_menu_renders_title_and_options_with_first_selected():
    menu, buffer, manager, selections = make_menu()
    assert row_text(buffer, 0) == "Horus Menu"
    assert row_text(buffer, 2) == "> Resume"
    assert row_text(buffer, 3) == "  Settings"
    assert row_text(buffer, 4) == "  Quit"


def test_menu_down_moves_selection_and_wraps():
    menu, buffer, manager, selections = make_menu()
    menu.handle_motion(key.MOTION_DOWN)
    assert menu._selected == 1
    assert row_text(buffer, 3) == "> Settings"
    menu.handle_motion(key.MOTION_DOWN)
    menu.handle_motion(key.MOTION_DOWN)  # 2 -> 0, wraps
    assert menu._selected == 0


def test_menu_up_moves_selection_and_wraps():
    menu, buffer, manager, selections = make_menu()
    menu.handle_motion(key.MOTION_UP)  # 0 -> last, wraps backward
    assert menu._selected == 2
    assert row_text(buffer, 4) == "> Quit"


def test_menu_enter_activates_selected_option():
    menu, buffer, manager, selections = make_menu()
    menu.handle_motion(key.MOTION_DOWN)
    menu.handle_enter()
    assert selections == ["Settings"]


def test_menu_escape_pops_itself_from_the_manager():
    menu, buffer, manager, selections = make_menu()
    assert manager.active is menu
    menu.handle_key(key.ESCAPE, 0)
    assert manager.active is None


def test_menu_ignores_typed_text():
    menu, buffer, manager, selections = make_menu()
    menu.handle_text("abc")  # should not raise, should not affect selection/options
    assert menu._selected == 0
