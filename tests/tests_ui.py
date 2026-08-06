import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen_manager import ScreenManager
from horus.ui.shell_screen import ShellScreen
from horus.ui.menu_screen import MenuScreen, MenuOption
from horus.ui.settings_screen import SettingScreen, SettingOption
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
    shell = ShellScreen(handler, manager)
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


def test_shell_screen_writes_prompt_on_push():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    handler = InputHandler(buffer, get_prompt=lambda: "> ")
    manager.push(ShellScreen(handler, manager))
    assert row_text(buffer, 0) == ">"


def test_shell_screen_redraws_prompt_after_plain_command():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    handler = InputHandler(buffer, get_prompt=lambda: "> ")
    manager.push(ShellScreen(handler, manager))
    manager.handle_text("hi")
    manager.handle_enter()  # no on_submit given, so nothing switches screens
    assert row_text(buffer, 1) == ">"


def test_shell_screen_does_not_clobber_a_screen_opened_from_enter():
    """Regression test: submitting a line that itself opens a menu (like the
    'horus' command) must not have the shell redraw its prompt on top of the
    menu that's now showing."""
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()

    def on_submit(line):
        if line == "horus":
            menu = MenuScreen(buffer, "Menu", [MenuOption("A", lambda: None)], manager)
            manager.push(menu)

    handler = InputHandler(buffer, on_submit=on_submit, get_prompt=lambda: "> ")
    shell = ShellScreen(handler, manager)
    manager.push(shell)
    manager.handle_text("horus")
    manager.handle_enter()
    assert manager.active is not shell
    assert row_text(buffer, 0) == "Menu"  # not clobbered by the shell's prompt


def test_shell_screen_redraws_prompt_when_menu_above_it_closes():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    handler = InputHandler(buffer, get_prompt=lambda: "> ")
    shell = ShellScreen(handler, manager)
    manager.push(shell)
    menu = MenuScreen(buffer, "Menu", [MenuOption("Back", lambda: manager.pop())], manager)
    manager.push(menu)
    assert row_text(buffer, 0) == "Menu"

    manager.handle_enter()  # activates "Back", pops the menu
    assert manager.active is shell
    assert row_text(buffer, 0) == ">"  # prompt redrawn, not left as "Menu"


def test_screen_manager_only_forwards_to_top_screen():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    handler = InputHandler(buffer)
    manager.push(ShellScreen(handler, manager))
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


def test_menu_disables_cursor_and_restores_it_on_pop():
    buffer = ScreenBuffer(30, 10)
    buffer.cursor_enabled = True  # e.g. the shell was showing before the menu opened
    manager = ScreenManager()
    menu = MenuScreen(buffer, "Menu", [MenuOption("A", lambda: None)], manager)
    manager.push(menu)
    assert buffer.cursor_enabled is False
    manager.pop()
    assert buffer.cursor_enabled is True


def test_returning_from_a_nested_menu_keeps_cursor_disabled():
    """Regression test: closing a settings screen that was opened from within
    another menu must leave the cursor disabled, since the menu underneath is
    still active -- not force it back on as if the shell was always underneath."""
    buffer = ScreenBuffer(30, 10)
    buffer.cursor_enabled = True
    manager = ScreenManager()
    menu = MenuScreen(buffer, "Menu", [MenuOption("A", lambda: None)], manager)
    manager.push(menu)
    assert buffer.cursor_enabled is False

    settings = SettingScreen(buffer, "Settings", [SettingOption("Return", on_select=lambda: manager.pop())], manager)
    manager.push(settings)
    assert buffer.cursor_enabled is False

    manager.pop()  # back to the menu -- cursor must stay disabled, not flip to True
    assert manager.active is menu
    assert buffer.cursor_enabled is False


# --- SettingScreen ---

def make_settings(cols=30, rows=10):
    buffer = ScreenBuffer(cols, rows)
    manager = ScreenManager()
    state = {"value": 1}

    def get_value():
        return str(state["value"])

    def step(delta):
        state["value"] += delta

    returned = []
    options = [
        SettingOption("Volume", get_value=get_value, on_left=lambda: step(-1), on_right=lambda: step(1)),
        SettingOption("Return", on_select=lambda: returned.append(True)),
    ]
    screen = SettingScreen(buffer, "Settings", options, manager)
    manager.push(screen)
    return screen, buffer, manager, state, returned


def test_settings_renders_title_and_value_with_first_selected():
    screen, buffer, manager, state, returned = make_settings()
    assert row_text(buffer, 0) == "Settings"
    assert row_text(buffer, 2) == "> Volume: < 1 >"
    assert row_text(buffer, 3) == "  Return"


def test_settings_right_increments_value_of_selected_option():
    screen, buffer, manager, state, returned = make_settings()
    screen.handle_motion(key.MOTION_RIGHT)
    assert state["value"] == 2
    assert row_text(buffer, 2) == "> Volume: < 2 >"


def test_settings_left_decrements_value_of_selected_option():
    screen, buffer, manager, state, returned = make_settings()
    screen.handle_motion(key.MOTION_LEFT)
    assert state["value"] == 0


def test_settings_left_right_on_option_without_handlers_is_a_no_op():
    screen, buffer, manager, state, returned = make_settings()
    screen.handle_motion(key.MOTION_DOWN)  # select "Return", which has no on_left/on_right
    screen.handle_motion(key.MOTION_LEFT)
    screen.handle_motion(key.MOTION_RIGHT)  # should not raise
    assert state["value"] == 1


def test_settings_enter_activates_on_select_of_selected_option():
    screen, buffer, manager, state, returned = make_settings()
    screen.handle_motion(key.MOTION_DOWN)
    screen.handle_enter()
    assert returned == [True]


def test_settings_enter_on_option_without_on_select_is_a_no_op():
    screen, buffer, manager, state, returned = make_settings()
    screen.handle_enter()  # "Volume" has no on_select; should not raise
    assert returned == []


def test_settings_escape_pops_itself_from_the_manager():
    screen, buffer, manager, state, returned = make_settings()
    assert manager.active is screen
    screen.handle_key(key.ESCAPE, 0)
    assert manager.active is None
