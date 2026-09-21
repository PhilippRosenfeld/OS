from unittest.mock import patch

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.display.status_bar import StatusBar
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable
from horus.session.history import CommandHistory
from horus.shell.input_handler import InputHandler
from horus.ui.box_drawing import draw_line_graph
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.boot_screen import BootFrame, BootScreen
from horus.ui.screens.crash_screen import CrashScreen
from horus.ui.screens.detail_screen import DetailScreen
from horus.ui.screens.hardware_screen import HardwareScreen, HardwareTile
from horus.ui.screens.loading_screen import LoadingScreen
from horus.ui.screens.logo_screen import LogoScreen
from horus.ui.screens.main_menu_screen import MainMenuScreen
from horus.ui.screens.main_menu_screen import MenuOption as MainMenuOption
from horus.ui.screens.menu_screen import MenuOption, MenuScreen
from horus.ui.screens.settings_screen import SettingOption, SettingScreen
from horus.ui.screens.shell_screen import ShellScreen
from horus.ui.screens.top_screen import TopScreen

key = pyglet.window.key


def row_text(buffer, row):
    return "".join(buffer.get_cell(c, row).char for c in range(buffer.cols)).rstrip()


# --- ScreenManager ---

def test_screen_manager_starts_with_no_active_screen():
    manager = ScreenManager()
    assert manager.active is None


def test_screen_manager_push_makes_screen_active_and_calls_on_push():
    manager = ScreenManager()
    screen = MenuScreen(ScreenBuffer(20, 5), "T", [MenuOption("A", lambda: None)], manager)
    manager.push(screen)
    assert manager.active is screen


def test_screen_manager_pop_restores_previous_screen():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history)
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


class RecordingScreen(Screen):
    """Minimal Screen that logs which lifecycle hooks fired, for pinning down
    exactly when on_push/on_pop/on_resume get called."""

    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    def on_push(self) -> None:
        self._events.append(f"{self._name}.on_push")

    def on_pop(self) -> None:
        self._events.append(f"{self._name}.on_pop")

    def on_resume(self) -> None:
        self._events.append(f"{self._name}.on_resume")

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        pass

    def handle_enter(self) -> None:
        pass

    def handle_key(self, symbol: int, modifiers: int) -> None:
        pass


def test_replace_swaps_the_top_screen():
    manager = ScreenManager()
    events = []
    first = RecordingScreen("first", events)
    second = RecordingScreen("second", events)
    manager.push(first)
    manager.replace(second)
    assert manager.active is second


def test_replace_does_not_fire_on_resume_on_the_screen_underneath():
    """Regression test: replace() must swap atomically -- pop() immediately
    followed by push() would synchronously (if briefly) reveal whatever is
    underneath and fire its on_resume(), which is exactly what caused the
    shell's cursor blink to start while the Logo screen was still covering it
    (Boot -> Logo used pop()+push() instead of replace())."""
    manager = ScreenManager()
    events = []
    bottom = RecordingScreen("bottom", events)
    top = RecordingScreen("top", events)
    manager.push(bottom)
    events.clear()

    manager.push(top)
    events.clear()
    manager.replace(RecordingScreen("replacement", events))

    assert "bottom.on_resume" not in events
    assert events == ["top.on_pop", "replacement.on_push"]


def test_replace_on_empty_stack_just_pushes():
    manager = ScreenManager()
    events = []
    screen = RecordingScreen("only", events)
    manager.replace(screen)
    assert manager.active is screen
    assert events == ["only.on_push"]


def test_on_active_changed_fires_on_push():
    seen = []
    manager = ScreenManager(on_active_changed=seen.append)
    screen = RecordingScreen("a", [])
    manager.push(screen)
    assert seen == [screen]


def test_on_active_changed_fires_on_pop_with_the_new_top():
    seen = []
    manager = ScreenManager(on_active_changed=seen.append)
    bottom = RecordingScreen("bottom", [])
    top = RecordingScreen("top", [])
    manager.push(bottom)
    manager.push(top)
    seen.clear()

    manager.pop()

    assert seen == [bottom]


def test_on_active_changed_fires_on_pop_to_empty_with_none():
    seen = []
    manager = ScreenManager(on_active_changed=seen.append)
    manager.push(RecordingScreen("only", []))
    seen.clear()

    manager.pop()

    assert seen == [None]


def test_on_active_changed_does_not_fire_on_pop_of_an_empty_stack():
    seen = []
    manager = ScreenManager(on_active_changed=seen.append)
    manager.pop()  # no-op, nothing was ever pushed
    assert seen == []


def test_on_active_changed_fires_on_replace():
    seen = []
    manager = ScreenManager(on_active_changed=seen.append)
    manager.push(RecordingScreen("first", []))
    seen.clear()

    replacement = RecordingScreen("second", [])
    manager.replace(replacement)

    assert seen == [replacement]


def test_without_on_active_changed_push_pop_replace_do_not_raise():
    manager = ScreenManager()  # no callback given
    manager.push(RecordingScreen("a", []))
    manager.replace(RecordingScreen("b", []))
    manager.pop()  # should not raise at any point


def test_status_bar_shows_only_while_the_shell_is_active():
    """Integration test for the actual feature (see horus.__init__'s
    ScreenManager(on_active_changed=...) wiring): the status bar becomes
    visible once the shell is pushed, hides again the moment something
    covers it (e.g. the 'horus' menu), and reappears once that's popped."""
    buffer = ScreenBuffer(40, 20)
    status_bar = StatusBar(40)
    manager = ScreenManager(on_active_changed=lambda screen: status_bar.set_visible(isinstance(screen, ShellScreen)))
    handler = InputHandler(buffer, CommandHistory())
    shell = ShellScreen(handler, manager)

    manager.push(shell)
    assert status_bar.is_visible() is True

    menu = MenuScreen(buffer, "Menu", [MenuOption("Back", lambda: manager.pop())], manager)
    manager.push(menu)
    assert status_bar.is_visible() is False

    manager.pop()  # back to shell
    assert status_bar.is_visible() is True


def test_shell_screen_writes_prompt_on_push():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: "> ")
    manager.push(ShellScreen(handler, manager))
    assert row_text(buffer, 0) == ">"


def test_shell_screen_redraws_prompt_after_plain_command():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: "> ")
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

    history = CommandHistory()
    handler = InputHandler(buffer, history, on_submit=on_submit, get_prompt=lambda: "> ")
    shell = ShellScreen(handler, manager)
    manager.push(shell)
    manager.handle_text("horus")
    manager.handle_enter()
    assert manager.active is not shell
    full = "".join(row_text(buffer, r) for r in range(buffer.rows))
    assert "Menu" in full  # not clobbered by the shell's prompt
    assert row_text(buffer, 0) == ""  # nothing (menu is centered, not pinned to the top)


def test_shell_screen_redraws_prompt_when_menu_above_it_closes():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: "> ")
    shell = ShellScreen(handler, manager)
    manager.push(shell)
    menu = MenuScreen(buffer, "Menu", [MenuOption("Back", lambda: manager.pop())], manager)
    manager.push(menu)
    assert "Menu" in "".join(row_text(buffer, r) for r in range(buffer.rows))

    manager.handle_enter()  # activates "Back", pops the menu
    assert manager.active is shell
    assert row_text(buffer, 0) == ">"  # prompt redrawn, not left as "Menu"


class FakeWindow:
    """Records .start_cursor_blink() calls instead of touching a real
    pyglet window/clock."""

    def __init__(self) -> None:
        self.blink_started_count = 0

    def start_cursor_blink(self) -> None:
        self.blink_started_count += 1


def test_shell_screen_on_push_does_not_start_cursor_blink():
    """Regression test: on_push() fires at app start, right before Boot gets
    pushed on top -- starting the blink there would flip cursor_visible
    underneath Boot/Logo/Main Menu too."""
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history)
    window = FakeWindow()
    shell = ShellScreen(handler, manager, window)
    manager.push(shell)  # on_push()
    assert window.blink_started_count == 0


def test_shell_screen_on_resume_starts_cursor_blink():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history)
    window = FakeWindow()
    shell = ShellScreen(handler, manager, window)
    manager.push(shell)
    assert window.blink_started_count == 0

    menu = MenuScreen(buffer, "Menu", [MenuOption("Back", lambda: manager.pop())], manager)
    manager.push(menu)
    manager.handle_enter()  # pops the menu -> shell.on_resume()
    assert window.blink_started_count == 1


def test_shell_screen_only_starts_cursor_blink_once():
    """Returning to the shell repeatedly (e.g. via the in-game menu) must not
    schedule a second concurrent blink timer -- that would make it flicker
    faster instead of blinking normally."""
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history)
    window = FakeWindow()
    shell = ShellScreen(handler, manager, window)
    manager.push(shell)

    for _ in range(3):
        menu = MenuScreen(buffer, "Menu", [MenuOption("Back", lambda: manager.pop())], manager)
        manager.push(menu)
        manager.handle_enter()

    assert window.blink_started_count == 1


def test_shell_screen_without_window_does_not_raise():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history)
    shell = ShellScreen(handler, manager)  # window=None
    manager.push(shell)
    menu = MenuScreen(buffer, "Menu", [MenuOption("Back", lambda: manager.pop())], manager)
    manager.push(menu)
    manager.handle_enter()  # should not raise


def test_shell_screen_escape_calls_on_escape_instead_of_the_input_handler():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history)
    calls = []
    shell = ShellScreen(handler, manager, on_escape=lambda: calls.append(True))
    manager.push(shell)
    shell.handle_key(key.ESCAPE, 0)
    assert calls == [True]


def test_shell_screen_escape_without_on_escape_falls_through_to_the_input_handler():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history)
    shell = ShellScreen(handler, manager)  # on_escape=None
    manager.push(shell)
    shell.handle_key(key.ESCAPE, 0)  # should not raise


def test_screen_manager_only_forwards_to_top_screen():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history)
    manager.push(ShellScreen(handler, manager))
    manager.handle_text("hi")
    assert handler.current_line == "hi"

    menu = MenuScreen(buffer, "T", [MenuOption("A", lambda: None)], manager)
    manager.push(menu)
    manager.handle_text("more")  # MenuScreen ignores text; must NOT reach the shell underneath
    assert handler.current_line == "hi"


# --- LoadingScreen ---

def test_loading_screen_disables_cursor_and_restores_it_on_pop():
    buffer = ScreenBuffer(30, 10)
    buffer.cursor_enabled = True
    manager = ScreenManager()
    loading = LoadingScreen(buffer, manager)
    manager.push(loading)
    assert buffer.cursor_enabled is False
    manager.pop()
    assert buffer.cursor_enabled is True


def test_loading_screen_swallows_all_input():
    buffer = ScreenBuffer(30, 10)
    manager = ScreenManager()
    manager.push(LoadingScreen(buffer, manager))
    manager.handle_text("hi")  # should not raise, and not go anywhere
    manager.handle_motion(key.MOTION_UP)
    manager.handle_enter()
    manager.handle_key(key.A, 0)
    assert manager.active is not None  # enter didn't pop it or anything else weird


def test_shell_does_not_redraw_its_prompt_while_a_loading_screen_is_up():
    """Regression test: a command (like encrypt/decrypt) that defers its real
    work via pyglet.clock and shows a progress bar in the meantime must push a
    screen over the shell for that duration -- otherwise ShellScreen.handle_enter()
    immediately redraws the prompt and re-enables the cursor on the very row
    the bar is animating on, since the command function itself already
    returned by then."""
    buffer = ScreenBuffer(40, 5)
    manager = ScreenManager()

    def on_submit(line):
        if line == "encrypt secret.txt":
            manager.push(LoadingScreen(buffer, manager))

    history = CommandHistory()
    handler = InputHandler(buffer, history, on_submit=on_submit, get_prompt=lambda: "> ")
    shell = ShellScreen(handler, manager)
    manager.push(shell)

    manager.handle_text("encrypt secret.txt")
    manager.handle_enter()

    assert isinstance(manager.active, LoadingScreen)
    assert buffer.cursor_enabled is False
    assert row_text(buffer, 1) == ""  # no fresh "> " prompt drawn over the bar's row

    manager.pop()  # simulates the bar completing
    assert manager.active is shell
    assert buffer.cursor_enabled is True
    assert row_text(buffer, 1) == ">"  # prompt only appears now


# --- TopScreen ---

def make_table():
    table = ProcessTable()
    table.add_process(Process(name="init", pid=0, owner="root", cpu_mhz=0.1, mem_kb=1024))
    return table


def test_top_screen_renders_the_process_table_on_push():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval"):
        manager.push(TopScreen(buffer, make_table(), manager))
    assert "init" in row_text(buffer, 3)


def test_top_screen_shows_a_combined_system_usage_summary():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    table = ProcessTable(total_memory_kb=10000, total_cpu_mhz=100)
    table.add_process(Process(name="a", pid=0, owner="root", cpu_mhz=30.0, mem_kb=2000))
    with patch("pyglet.clock.schedule_interval"):
        manager.push(TopScreen(buffer, table, manager))
    assert "System:" in row_text(buffer, 0)
    assert "30/100 MHz" in row_text(buffer, 0)
    assert "2000/10000 KB" in row_text(buffer, 0)


def test_top_screen_disables_cursor_and_restores_it_on_pop():
    buffer = ScreenBuffer(60, 10)
    buffer.cursor_enabled = True
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval"):
        manager.push(TopScreen(buffer, make_table(), manager))
    assert buffer.cursor_enabled is False
    manager.pop()
    assert buffer.cursor_enabled is True


def test_top_screen_schedules_a_recurring_refresh():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        screen = TopScreen(buffer, make_table(), manager, refresh_interval=2.0)
        manager.push(screen)
    callback, interval = mock_schedule.call_args[0]
    assert interval == 2.0
    assert callback == screen._tick


def test_top_screen_refresh_reflects_new_processes():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    table = make_table()
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        screen = TopScreen(buffer, table, manager)
        manager.push(screen)
    table.add_process(Process(name="new_proc", pid=0, owner="user1", cpu_mhz=2.5, mem_kb=4096))
    callback, _ = mock_schedule.call_args[0]
    callback(0.0)
    screen_text = "".join(row_text(buffer, r) for r in range(buffer.rows))
    assert "new_proc" in screen_text  # row position isn't fixed -- rows are sorted by cpu usage


def test_top_screen_tick_is_a_noop_while_covered_by_an_externally_pushed_screen():
    """See the matching HardwareScreen regression test: a CrashScreen pushed
    by an event reaction while top is open must not get clobbered by top's
    own still-running tick."""
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval"):
        screen = TopScreen(buffer, make_table(), manager)
        manager.push(screen)

    with patch("pyglet.clock.schedule_once"):
        manager.push(CrashScreen(buffer, None, "hog"))
    screen._tick(dt=0.0)  # must not raise, and must not re-render over the crash screen

    screen_text = "".join(row_text(buffer, r) for r in range(buffer.rows))
    assert "KERNEL PANIC" in screen_text


def test_top_screen_ctrl_c_pops_back_to_the_shell():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: "> ")
    shell = ShellScreen(handler, manager)
    manager.push(shell)
    with patch("pyglet.clock.schedule_interval"):
        manager.push(TopScreen(buffer, make_table(), manager))
    assert manager.active is not shell

    manager.handle_key(key.C, key.MOD_CTRL)
    assert manager.active is shell


def test_top_screen_plain_c_without_ctrl_does_not_exit():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval"):
        screen = TopScreen(buffer, make_table(), manager)
        manager.push(screen)
    manager.handle_key(key.C, 0)
    assert manager.active is screen


def test_top_screen_unschedules_the_refresh_on_pop():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval"):
        screen = TopScreen(buffer, make_table(), manager)
        manager.push(screen)
    with patch("pyglet.clock.unschedule") as mock_unschedule:
        manager.pop()
    mock_unschedule.assert_called_once_with(screen._tick)


def test_top_screen_ignores_text_motion_and_enter():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval"):
        manager.push(TopScreen(buffer, make_table(), manager))
    manager.handle_text("hi")  # should not raise, and not act on it
    manager.handle_motion(key.MOTION_UP)
    manager.handle_enter()
    assert isinstance(manager.active, TopScreen)


# --- CrashScreen ---

class FakeCloseableWindow:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_crash_screen_renders_a_kernel_panic_message_and_disables_cursor():
    buffer = ScreenBuffer(60, 10)
    buffer.cursor_enabled = True
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_once"):
        manager.push(CrashScreen(buffer, FakeCloseableWindow(), "init"))
    assert buffer.cursor_enabled is False
    screen_text = "".join(row_text(buffer, r) for r in range(buffer.rows))
    assert "KERNEL PANIC" in screen_text
    assert "init" in screen_text


def test_crash_screen_default_reason_says_terminated_unexpectedly():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_once"):
        manager.push(CrashScreen(buffer, FakeCloseableWindow(), "init"))
    screen_text = "".join(row_text(buffer, r) for r in range(buffer.rows))
    assert "terminated unexpectedly" in screen_text


def test_crash_screen_shows_a_custom_reason():
    """A CrashScreen pushed for a specific cause (e.g. a thermal shutdown)
    must say so, not just name the process."""
    buffer = ScreenBuffer(100, 10)  # wide enough that the message doesn't wrap across rows
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_once"):
        manager.push(CrashScreen(buffer, FakeCloseableWindow(), "hog",
                                  reason="killed due to critical temperature (95.0C)"))
    screen_text = "".join(row_text(buffer, r) for r in range(buffer.rows))
    assert "hog" in screen_text
    assert "killed due to critical temperature (95.0C)" in screen_text


def test_crash_screen_schedules_the_window_close_after_a_delay():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_once") as mock_schedule:
        screen = CrashScreen(buffer, FakeCloseableWindow(), "init", delay=7.0)
        manager.push(screen)
    callback, delay = mock_schedule.call_args[0]
    assert delay == 7.0
    assert callback == screen._close_window


def test_crash_screen_closes_the_window_once_the_delay_elapses():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    window = FakeCloseableWindow()
    with patch("pyglet.clock.schedule_once") as mock_schedule:
        manager.push(CrashScreen(buffer, window, "init"))
    callback, _ = mock_schedule.call_args[0]
    assert window.closed is False
    callback(0.0)
    assert window.closed is True


def test_crash_screen_without_a_window_does_not_raise_on_close():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_once") as mock_schedule:
        manager.push(CrashScreen(buffer, None, "init"))
    callback, _ = mock_schedule.call_args[0]
    callback(0.0)  # should not raise


def test_crash_screen_ignores_all_input():
    buffer = ScreenBuffer(60, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_once"):
        manager.push(CrashScreen(buffer, FakeCloseableWindow(), "init"))
    manager.handle_text("hi")  # should not raise, and not act on it
    manager.handle_motion(key.MOTION_UP)
    manager.handle_enter()
    manager.handle_key(key.A, 0)
    assert isinstance(manager.active, CrashScreen)  # still frozen on the crash screen


# --- MenuScreen ---

def make_menu(cols=30, rows=10, labels=("Resume", "Settings", "Quit")):
    buffer = ScreenBuffer(cols, rows)
    manager = ScreenManager()
    selections = []
    options = [MenuOption(label, (lambda selected=label: selections.append(selected))) for label in labels]
    menu = MenuScreen(buffer, "Horus Menu", options, manager)
    manager.push(menu)
    return menu, buffer, manager, selections


# make_menu() uses a 30x10 buffer with labels ("Resume", "Settings", "Quit")
# (widest line "  Settings" is 10 chars, block is 5 rows tall) -- centered
# that's row 2, col 10. See MenuScreen._render().
_MENU_ROW = 2
_MENU_COL = 10


def test_menu_renders_title_and_options_with_first_selected():
    menu, buffer, manager, selections = make_menu()
    assert row_text(buffer, _MENU_ROW) == " " * _MENU_COL + "Horus Menu"
    assert row_text(buffer, _MENU_ROW + 2) == " " * _MENU_COL + "> Resume"
    assert row_text(buffer, _MENU_ROW + 3) == " " * _MENU_COL + "  Settings"
    assert row_text(buffer, _MENU_ROW + 4) == " " * _MENU_COL + "  Quit"


def test_menu_is_centered_not_pinned_to_the_top_left():
    menu, buffer, manager, selections = make_menu()
    assert row_text(buffer, 0) == ""  # nothing flush against the top
    assert row_text(buffer, _MENU_ROW).startswith(" ")  # nothing flush against the left


def test_menu_down_moves_selection_and_wraps():
    menu, buffer, manager, selections = make_menu()
    menu.handle_motion(key.MOTION_DOWN)
    assert menu._selected == 1
    assert row_text(buffer, _MENU_ROW + 3) == " " * _MENU_COL + "> Settings"
    menu.handle_motion(key.MOTION_DOWN)
    menu.handle_motion(key.MOTION_DOWN)  # 2 -> 0, wraps
    assert menu._selected == 0


def test_menu_up_moves_selection_and_wraps():
    menu, buffer, manager, selections = make_menu()
    menu.handle_motion(key.MOTION_UP)  # 0 -> last, wraps backward
    assert menu._selected == 2
    assert row_text(buffer, _MENU_ROW + 4) == " " * _MENU_COL + "> Quit"


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


# --- MainMenuScreen ---

def test_main_menu_title_is_horizontally_centered():
    buffer = ScreenBuffer(80, 24)
    title = "H O R U S   S Y S T E M S"
    screen = MainMenuScreen(buffer, title, [MainMenuOption("Continue", lambda: None)])
    screen.on_push()
    row = next(r for r in range(buffer.rows) if row_text(buffer, r))
    text = row_text(buffer, row)
    left_margin = len(text) - len(text.lstrip())
    right_margin = buffer.cols - left_margin - len(title)
    # roughly symmetric: left gap and right gap differ by at most 1 column (integer division)
    assert abs(left_margin - right_margin) <= 1


def test_main_menu_options_block_centers_on_actual_label_width_not_a_hardcoded_one():
    """Regression test: the options block used to center itself around a
    hardcoded width of 20 columns regardless of the labels' real length, so
    for short labels (e.g. 'Exit') the whole block -- and by extension the
    title above it -- no longer looked centered as a cohesive unit."""
    buffer = ScreenBuffer(80, 24)
    options = [MainMenuOption("Continue", lambda: None), MainMenuOption("Exit", lambda: None)]
    screen = MainMenuScreen(buffer, "TITLE", options)
    screen.on_push()

    continue_row = next(r for r in range(buffer.rows) if "Continue" in row_text(buffer, r))
    text = row_text(buffer, continue_row)
    left_margin = len(text) - len(text.lstrip())
    widest = len("Continue") + 2  # +2 for the "> "/"  " prefix
    assert left_margin == max(0, (buffer.cols - widest) // 2)


def test_main_menu_options_share_a_common_left_edge():
    buffer = ScreenBuffer(80, 24)
    options = [MainMenuOption("Continue", lambda: None), MainMenuOption("Settings", lambda: None), MainMenuOption("Exit", lambda: None)]
    screen = MainMenuScreen(buffer, "TITLE", options)
    screen.on_push()

    # look at where each label's own text starts (ignoring the "> "/"  "
    # prefix, which is the same width either way) -- these must all line up
    positions = {}
    for label in ("Continue", "Settings", "Exit"):
        row = next(r for r in range(buffer.rows) if label in row_text(buffer, r))
        positions[label] = row_text(buffer, row).index(label)
    assert len(set(positions.values())) == 1


def test_main_menu_fades_in_the_theme_song_on_first_push():
    buffer = ScreenBuffer(80, 24)
    sounds = FakeSounds()
    screen = MainMenuScreen(buffer, "TITLE", [MainMenuOption("Continue", lambda: None)],
                             sounds=sounds, song="menu_theme", song_volume=0.4, song_fade_in=3.0)
    screen.on_push()
    assert sounds.fade_ins == [("menu_theme", 0.4, 3.0, True)]


def test_main_menu_without_song_does_not_touch_sounds():
    buffer = ScreenBuffer(80, 24)
    sounds = FakeSounds()
    screen = MainMenuScreen(buffer, "TITLE", [MainMenuOption("Continue", lambda: None)], sounds=sounds)  # song=None
    screen.on_push()
    assert sounds.fade_ins == []


def test_main_menu_without_sounds_does_not_raise():
    buffer = ScreenBuffer(80, 24)
    screen = MainMenuScreen(buffer, "TITLE", [MainMenuOption("Continue", lambda: None)], song="menu_theme")  # sounds=None
    screen.on_push()  # should not raise


def test_main_menu_does_not_restart_the_song_on_resume():
    """The theme must keep looping uninterrupted while a submenu (e.g.
    Settings) is open on top -- on_resume() must not fade it in again."""
    buffer = ScreenBuffer(80, 24)
    sounds = FakeSounds()
    manager = ScreenManager()
    screen = MainMenuScreen(buffer, "TITLE", [MainMenuOption("Continue", lambda: None)],
                             sounds=sounds, song="menu_theme")
    manager.push(screen)
    assert len(sounds.fade_ins) == 1

    settings = SettingScreen(buffer, "Settings", [SettingOption("Return", on_select=lambda: manager.pop())], manager)
    manager.push(settings)
    manager.pop()  # back to the main menu -> on_resume()
    assert len(sounds.fade_ins) == 1  # still just the one fade-in from on_push()


def test_main_menu_fades_out_the_song_on_pop():
    """Regression test: on_pop() used to cut the theme off with a plain
    .pause() -- picking 'Continue' should fade it out instead."""
    buffer = ScreenBuffer(80, 24)
    sounds = FakeSounds()
    screen = MainMenuScreen(buffer, "TITLE", [MainMenuOption("Continue", lambda: None)],
                             sounds=sounds, song="menu_theme", song_fade_out=3.0)
    screen.on_push()
    player = screen._song_player
    assert player.playing is True

    screen.on_pop()
    assert sounds.fades == [(0.0, 3.0)]  # faded out, not abruptly cut
    assert player.paused_count == 1  # ...but still actually stopped once silent (FakeSounds.fade_out fires on_complete immediately)
    assert screen._song_player is None


def test_main_menu_fade_out_is_scoped_to_its_own_player():
    """Regression test: on_pop() used to call fade_out() without a `player`,
    which fades every currently-playing sound -- if another track (e.g. a
    separately looping background song) happened to be playing/fading in at
    the same time, it got dragged into the menu theme's fade-out too."""
    buffer = ScreenBuffer(80, 24)
    sounds = FakeSounds()
    screen = MainMenuScreen(buffer, "TITLE", [MainMenuOption("Continue", lambda: None)],
                             sounds=sounds, song="menu_theme")
    screen.on_push()
    player = screen._song_player

    screen.on_pop()
    assert sounds.faded_players == [player]


def test_main_menu_pop_without_a_song_does_not_touch_sounds():
    buffer = ScreenBuffer(80, 24)
    sounds = FakeSounds()
    screen = MainMenuScreen(buffer, "TITLE", [MainMenuOption("Continue", lambda: None)], sounds=sounds)  # song=None
    screen.on_push()
    screen.on_pop()  # should not raise
    assert sounds.fades == []


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


# make_settings() uses a 30x10 buffer with options ["Volume: < 1 >", "Return"]
# (widest line "> Volume: < 1 >" is 15 chars, block is 4 rows tall) -- centered
# that's row 3, col 7. See SettingScreen._render().
_SETTINGS_ROW = 3
_SETTINGS_COL = 7


def test_settings_renders_title_and_value_with_first_selected():
    screen, buffer, manager, state, returned = make_settings()
    assert row_text(buffer, _SETTINGS_ROW) == " " * _SETTINGS_COL + "Settings"
    assert row_text(buffer, _SETTINGS_ROW + 2) == " " * _SETTINGS_COL + "> Volume: < 1 >"
    assert row_text(buffer, _SETTINGS_ROW + 3) == " " * _SETTINGS_COL + "  Return"


def test_settings_is_centered_not_pinned_to_the_top_left():
    screen, buffer, manager, state, returned = make_settings()
    assert row_text(buffer, 0) == ""  # nothing flush against the top
    assert row_text(buffer, _SETTINGS_ROW).startswith(" ")  # nothing flush against the left


def test_settings_right_increments_value_of_selected_option():
    screen, buffer, manager, state, returned = make_settings()
    screen.handle_motion(key.MOTION_RIGHT)
    assert state["value"] == 2
    assert row_text(buffer, _SETTINGS_ROW + 2) == " " * _SETTINGS_COL + "> Volume: < 2 >"


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


def test_settings_render_resets_writes_instead_of_accumulating():
    """Regression test: _render() ran on every keypress (Up/Down/Left/Right)
    without clearing first, so _writes (the replay log a later resize uses)
    grew by a full render's worth of write_string calls every time. A resize
    triggered while the screen was showing (e.g. font size change shrinking
    cols) would then replay every past render's writes -- including ones with
    now-stale, differently-wrapped content -- producing garbled artifacts."""
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()
    option = SettingOption("Vol", get_value=lambda: "1")
    screen = SettingScreen(buffer, "Settings", [option, SettingOption("Return")], manager)
    manager.push(screen)  # on_push() -> one _render()
    writes_after_one_render = len(buffer._writes)
    assert writes_after_one_render > 0

    screen._render()
    screen._render()
    screen._render()

    assert len(buffer._writes) == writes_after_one_render


def test_settings_resize_mid_session_does_not_leave_artifacts():
    """End-to-end version of the same regression: cycling a setting that
    shrinks the buffer's cols (as a bigger font would) must not leave stale,
    differently-wrapped text lingering from before the resize."""
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()

    def shrink() -> None:
        buffer.resize(15, 10)  # simulates a font-size bump shrinking the grid

    options = [
        SettingOption("Window Size", get_value=lambda: "1600x900", on_right=shrink),
        SettingOption("Return"),
    ]
    screen = SettingScreen(buffer, "Settings", options, manager)
    manager.push(screen)
    screen.handle_motion(key.MOTION_RIGHT)  # shrinks cols, then re-renders at the new width

    full = "".join(row_text(buffer, r) for r in range(buffer.rows))
    assert "Settings" in full
    assert "Window Size" in full
    for row in range(buffer.rows):
        assert "900" not in row_text(buffer, row)  # no wrapped/stale tail from the wider render


# --- HardwareScreen ---

def make_hardware(cols=40, rows=20):
    buffer = ScreenBuffer(cols, rows)
    manager = ScreenManager()
    selections = []

    def make_tile(label, *lines):
        return HardwareTile(label, list(lines), on_select=lambda: selections.append(label))

    overview = make_tile("Overview", "CPU 5%  RAM 10%")
    cpu = make_tile("CPU", "Core i9", "3.2 GHz")
    ram = make_tile("RAM", "16 GB")
    storage = make_tile("Storage", "500 GB SSD")
    external = make_tile("External")
    power = make_tile("Power", "Horus PSU", "500 W")
    cooling = make_tile("Cooling", "Water", "99%")
    network = make_tile("Network", "eth0: 10.0.0.2")
    screen = HardwareScreen(buffer, "Hardware", overview, cpu, ram, storage, external, power, cooling, network, manager)
    manager.push(screen)
    return screen, buffer, manager, selections


def test_hardware_screen_lays_out_the_external_tile_with_nested_subtiles():
    """40x20 buffer: header is 4 rows, leaving a 16-row body. The left column
    (cols 0-19) stacks CPU(6)/RAM(5)/Storage(5) directly. The right column
    (cols 20-39) is one outer 'External' tile spanning the full height, with
    Power/Cooling/Network nested inside its interior (inset by 1 cell on
    every side), themselves split 5/5/4 across the 14-row interior. See
    HardwareScreen._render()."""
    screen, buffer, manager, selections = make_hardware()

    assert row_text(buffer, 0).startswith("+ Overview ")  # label embedded in the top border
    assert "CPU 5%  RAM 10%" in row_text(buffer, 2)
    assert row_text(buffer, 3) == "+" + "-" * 38 + "+"  # bottom border has no label, stays plain

    assert row_text(buffer, 4)[:20].startswith("+ CPU ")
    assert "Core i9" in row_text(buffer, 6)[:20]
    assert "3.2 GHz" in row_text(buffer, 7)[:20]
    assert row_text(buffer, 9)[:20] == "+" + "-" * 18 + "+"  # CPU's own bottom border, 6 rows tall

    assert row_text(buffer, 10)[:20].startswith("+ RAM ")
    assert "16 GB" in row_text(buffer, 12)[:20]
    assert row_text(buffer, 14)[:20] == "+" + "-" * 18 + "+"  # RAM's bottom border, 5 rows tall

    assert row_text(buffer, 15)[:20].startswith("+ Storage ")
    assert "500 GB SSD" in row_text(buffer, 17)[:20]
    assert row_text(buffer, 19)[:20] == "+" + "-" * 18 + "+"  # Storage's bottom border

    # External: one outer box spanning the whole right column...
    assert row_text(buffer, 4)[20:].startswith("+ External ")
    assert row_text(buffer, 19)[20:] == "+" + "-" * 18 + "+"

    # ...with Power/Cooling/Network nested inside it, inset by 1 cell.
    assert row_text(buffer, 5)[21:].startswith("+ Power ")
    assert "Horus PSU" in row_text(buffer, 7)[21:]
    assert row_text(buffer, 9)[21:39] == "+" + "-" * 16 + "+"  # Power's own bottom border

    assert row_text(buffer, 10)[21:].startswith("+ Cooling ")
    assert "Water" in row_text(buffer, 12)[21:]
    assert row_text(buffer, 14)[21:39] == "+" + "-" * 16 + "+"  # Cooling's own bottom border

    assert row_text(buffer, 15)[21:].startswith("+ Network ")
    assert "eth0: 10.0.0.2" in row_text(buffer, 17)[21:]
    assert row_text(buffer, 18)[21:39] == "+" + "-" * 16 + "+"  # Network's own bottom border


def test_hardware_screen_cpu_tile_is_selected_first():
    screen, buffer, manager, selections = make_hardware()
    cpu_corner = buffer.get_cell(0, 4)
    assert cpu_corner.fg_color == buffer.default_bg
    assert cpu_corner.bg_color == buffer.default_fg

    power_corner = buffer.get_cell(21, 5)  # nested Power tile, not selected
    assert power_corner.fg_color == buffer.default_fg
    assert power_corner.bg_color == buffer.default_bg


def test_hardware_screen_external_tile_itself_is_never_selected():
    """Only its nested sub-tiles (Power/Cooling/Network) are selectable --
    the outer External box is just a grouping container."""
    screen, buffer, manager, selections = make_hardware()
    screen.handle_motion(key.MOTION_RIGHT)
    external_corner = buffer.get_cell(20, 4)
    assert external_corner.fg_color == buffer.default_fg
    assert external_corner.bg_color == buffer.default_bg


def test_hardware_screen_right_moves_selection_to_the_right_column():
    screen, buffer, manager, selections = make_hardware()
    screen.handle_motion(key.MOTION_RIGHT)
    assert screen._selected_col == 1
    assert buffer.get_cell(21, 5).fg_color == buffer.default_bg  # Power's corner now highlighted


def test_hardware_screen_down_moves_through_the_left_column():
    screen, buffer, manager, selections = make_hardware()
    screen.handle_motion(key.MOTION_DOWN)
    assert (screen._selected_col, screen._selected_row) == (0, 1)  # RAM
    screen.handle_motion(key.MOTION_DOWN)
    assert (screen._selected_col, screen._selected_row) == (0, 2)  # Storage


def test_hardware_screen_down_moves_through_the_right_column():
    screen, buffer, manager, selections = make_hardware()
    screen.handle_motion(key.MOTION_RIGHT)  # PSU
    screen.handle_motion(key.MOTION_DOWN)
    assert (screen._selected_col, screen._selected_row) == (1, 1)  # Cooling
    screen.handle_motion(key.MOTION_DOWN)
    assert (screen._selected_col, screen._selected_row) == (1, 2)  # Network


def test_hardware_screen_leaving_and_returning_to_the_left_column_keeps_its_row():
    screen, buffer, manager, selections = make_hardware()
    screen.handle_motion(key.MOTION_DOWN)  # RAM (row 1)
    screen.handle_motion(key.MOTION_RIGHT)  # right column, same row -> Cooling
    screen.handle_motion(key.MOTION_LEFT)  # back to the left column
    assert (screen._selected_col, screen._selected_row) == (0, 1)  # still RAM, not reset to CPU


def test_hardware_screen_up_down_wrap_around_the_left_column():
    screen, buffer, manager, selections = make_hardware()
    screen.handle_motion(key.MOTION_UP)  # 0 -> wraps to 2 (Storage)
    assert screen._selected_row == 2
    screen.handle_motion(key.MOTION_DOWN)  # 2 -> wraps to 0 (CPU)
    assert screen._selected_row == 0


def test_hardware_screen_up_down_wrap_around_the_right_column():
    screen, buffer, manager, selections = make_hardware()
    screen.handle_motion(key.MOTION_RIGHT)
    screen.handle_motion(key.MOTION_UP)  # 0 -> wraps to 2 (Network)
    assert screen._selected_row == 2
    screen.handle_motion(key.MOTION_DOWN)  # 2 -> wraps to 0 (PSU)
    assert screen._selected_row == 0


def test_hardware_screen_enter_activates_the_selected_tile():
    screen, buffer, manager, selections = make_hardware()
    screen.handle_motion(key.MOTION_DOWN)  # RAM row (row 1)
    screen.handle_motion(key.MOTION_RIGHT)  # same row, right column -> Cooling
    screen.handle_enter()
    assert selections == ["Cooling"]


def test_hardware_screen_enter_pauses_its_own_tick_while_a_detail_screen_is_open():
    """Regression test: HardwareScreen used to keep ticking (and
    re-rendering onto the shared buffer) even while a tile's detail screen
    was pushed on top of it -- the two would clobber each other's content
    every tick, flickering back and forth between overview and detail."""
    buffer = ScreenBuffer(40, 20)
    manager = ScreenManager()
    tile = HardwareTile("X")
    selected = HardwareTile("CPU", on_select=lambda: None)
    with patch("pyglet.clock.schedule_interval"):
        screen = HardwareScreen(buffer, "Hardware", tile, selected, tile, tile, tile, tile, tile, tile,
                                 manager, refresh=lambda: None)
        manager.push(screen)
    with patch("pyglet.clock.unschedule") as mock_unschedule:
        screen.handle_enter()
    mock_unschedule.assert_called_once_with(screen._tick)


def test_hardware_screen_tick_is_a_noop_while_covered_by_an_externally_pushed_screen():
    """Regression test: a screen can also end up covering HardwareScreen from
    outside its own code entirely -- e.g. a CrashScreen pushed by a
    temperature/power event reaction while HardwareScreen is active.
    handle_enter()'s unschedule can't help there (HardwareScreen never gets a
    chance to react before being covered), so _tick must guard itself
    instead, or it keeps clobbering the CrashScreen's content every tick,
    flickering back and forth between it and the overview."""
    buffer = ScreenBuffer(40, 20)
    manager = ScreenManager()
    tile = HardwareTile("X")
    calls = []
    with patch("pyglet.clock.schedule_interval"):
        screen = HardwareScreen(buffer, "Hardware", tile, tile, tile, tile, tile, tile, tile, tile,
                                 manager, refresh=lambda: calls.append(True))
        manager.push(screen)
    calls.clear()  # drop the call from on_push()'s own initial render

    with patch("pyglet.clock.schedule_once"):
        manager.push(CrashScreen(buffer, None, "hog"))  # covers HardwareScreen from outside
    screen._tick(dt=0.0)

    assert calls == []  # refresh() was not called -- the tick no-op'd instead of rendering over the crash screen


def test_hardware_screen_on_resume_reschedules_the_tick_and_rerenders():
    buffer = ScreenBuffer(40, 20)
    manager = ScreenManager()
    tile = HardwareTile("X")
    calls = []
    with patch("pyglet.clock.schedule_interval"):
        screen = HardwareScreen(buffer, "Hardware", tile, tile, tile, tile, tile, tile, tile, tile,
                                 manager, refresh=lambda: calls.append(True))
        manager.push(screen)
    calls.clear()  # drop the call from on_push()'s own initial render

    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        screen.on_resume()
    assert calls == [True]  # refreshed before redrawing, not left stale
    mock_schedule.assert_called_once_with(screen._tick, screen._refresh_interval)


def test_hardware_screen_escape_pops_itself_from_the_manager():
    screen, buffer, manager, selections = make_hardware()
    assert manager.active is screen
    screen.handle_key(key.ESCAPE, 0)
    assert manager.active is None


def test_hardware_screen_disables_cursor_and_restores_it_on_pop():
    buffer = ScreenBuffer(40, 20)
    buffer.cursor_enabled = True
    manager = ScreenManager()
    tile = HardwareTile("X")
    screen = HardwareScreen(buffer, "Hardware", tile, tile, tile, tile, tile, tile, tile, tile, manager)
    manager.push(screen)
    assert buffer.cursor_enabled is False
    manager.pop()
    assert buffer.cursor_enabled is True


def test_hardware_screen_without_refresh_does_not_schedule_anything():
    """Default behavior (no `refresh` given) stays exactly as before this
    existed: static tiles, no pyglet.clock involvement."""
    screen, buffer, manager, selections = make_hardware()
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        screen.on_push()
    mock_schedule.assert_not_called()


def test_hardware_screen_with_refresh_schedules_a_recurring_tick():
    buffer = ScreenBuffer(40, 20)
    manager = ScreenManager()
    tile = HardwareTile("X")
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        screen = HardwareScreen(buffer, "Hardware", tile, tile, tile, tile, tile, tile, tile, tile,
                                 manager, refresh=lambda: None, refresh_interval=2.0)
        manager.push(screen)
    mock_schedule.assert_called_once()
    callback, interval = mock_schedule.call_args[0]
    assert interval == 2.0
    assert callback == screen._tick


def test_hardware_screen_tick_calls_refresh_then_rerenders():
    buffer = ScreenBuffer(40, 20)
    manager = ScreenManager()
    overview = HardwareTile("Overview")
    tile = HardwareTile("X")
    calls = []

    def refresh():
        calls.append(True)
        overview.lines = ["updated"]

    with patch("pyglet.clock.schedule_interval"):
        screen = HardwareScreen(buffer, "Hardware", overview, tile, tile, tile, tile, tile, tile, tile,
                                 manager, refresh=refresh)
        manager.push(screen)
    assert calls == []  # not called yet -- only on_push()'s own initial _render()

    screen._tick(dt=0.0)
    assert calls == [True]
    assert "updated" in row_text(buffer, 2)


def test_hardware_screen_unschedules_the_tick_on_pop():
    buffer = ScreenBuffer(40, 20)
    manager = ScreenManager()
    tile = HardwareTile("X")
    with patch("pyglet.clock.schedule_interval"):
        screen = HardwareScreen(buffer, "Hardware", tile, tile, tile, tile, tile, tile, tile, tile,
                                 manager, refresh=lambda: None)
        manager.push(screen)
    with patch("pyglet.clock.unschedule") as mock_unschedule:
        manager.pop()
    mock_unschedule.assert_called_once_with(screen._tick)


# --- DetailScreen ---

def test_hardware_detail_screen_renders_title_and_lines():
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()
    screen = DetailScreen(buffer, "CPU", ["Coeles X3201", "Cores: 1"], manager)
    manager.push(screen)
    assert row_text(buffer, 0).startswith("+ CPU ")
    assert "Coeles X3201" in row_text(buffer, 2)
    assert "Cores: 1" in row_text(buffer, 3)


def test_hardware_detail_screen_disables_cursor_and_restores_it_on_pop():
    buffer = ScreenBuffer(40, 10)
    buffer.cursor_enabled = True
    manager = ScreenManager()
    screen = DetailScreen(buffer, "CPU", ["line"], manager)
    manager.push(screen)
    assert buffer.cursor_enabled is False
    manager.pop()
    assert buffer.cursor_enabled is True


def test_hardware_detail_screen_escape_pops_itself_from_the_manager():
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()
    screen = DetailScreen(buffer, "CPU", ["line"], manager)
    manager.push(screen)
    assert manager.active is screen
    screen.handle_key(key.ESCAPE, 0)
    assert manager.active is None


def test_hardware_detail_screen_without_refresh_does_not_schedule_anything():
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()
    screen = DetailScreen(buffer, "CPU", ["line"], manager)
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        screen.on_push()
    mock_schedule.assert_not_called()


def test_hardware_detail_screen_with_refresh_schedules_a_recurring_tick():
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        screen = DetailScreen(buffer, "CPU", ["line"], manager,
                                       refresh=lambda: ["line"], refresh_interval=2.0)
        manager.push(screen)
    mock_schedule.assert_called_once()
    callback, interval = mock_schedule.call_args[0]
    assert interval == 2.0
    assert callback == screen._tick


def test_hardware_detail_screen_tick_calls_refresh_then_rerenders():
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()
    calls = []

    def refresh():
        calls.append(True)
        return ["updated line"]

    with patch("pyglet.clock.schedule_interval"):
        screen = DetailScreen(buffer, "CPU", ["stale line"], manager, refresh=refresh)
        manager.push(screen)
    assert calls == []  # not called yet -- only on_push()'s own initial _render()

    screen._tick(dt=0.0)
    assert calls == [True]
    assert "updated line" in row_text(buffer, 2)


def test_hardware_detail_screen_tick_is_a_noop_while_covered_by_an_externally_pushed_screen():
    """See the matching HardwareScreen regression test: a CrashScreen pushed
    by an event reaction while a detail screen is open must not get
    clobbered by the detail screen's own still-running tick."""
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()
    calls = []

    def refresh():
        calls.append(True)
        return ["updated line"]

    with patch("pyglet.clock.schedule_interval"):
        screen = DetailScreen(buffer, "CPU", ["stale line"], manager, refresh=refresh)
        manager.push(screen)

    with patch("pyglet.clock.schedule_once"):
        manager.push(CrashScreen(buffer, None, "hog"))
    screen._tick(dt=0.0)

    assert calls == []


def test_hardware_detail_screen_unschedules_the_tick_on_pop():
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval"):
        screen = DetailScreen(buffer, "CPU", ["line"], manager, refresh=lambda: ["line"])
        manager.push(screen)
    with patch("pyglet.clock.unschedule") as mock_unschedule:
        manager.pop()
    mock_unschedule.assert_called_once_with(screen._tick)


# --- DetailScreen with history_fn (line-graph layout) ---

def test_hardware_detail_screen_without_history_fn_keeps_the_single_full_width_box():
    """Every panel that doesn't pass history_fn keeps today's layout exactly
    -- one box spanning the whole buffer, same as before this existed."""
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    screen = DetailScreen(buffer, "CPU", ["line"], manager)
    manager.push(screen)
    assert buffer.get_cell(0, 0).char == "+"
    assert buffer.get_cell(59, 0).char == "+"
    assert buffer.get_cell(30, 0).char == "-"  # unbroken border -- no second box starting mid-row


def test_hardware_detail_screen_with_history_fn_splits_into_three_regions():
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    screen = DetailScreen(buffer, "Cooling", ["Coolant System", "Draw: 5 W"], manager,
                           history_fn=lambda: [1.0, 2.0, 3.0], history_title="Cooling draw (W)")
    manager.push(screen)

    assert "Coolant System" in row_text(buffer, 2)  # left column: the usual data lines
    left_width = buffer.cols // 2
    assert row_text(buffer, 0)[left_width] == "+"  # a second box starts right where the left one ends
    top_height = buffer.rows // 2
    assert "Cooling draw (W)" in row_text(buffer, top_height)  # bottom-right box is the graph, labeled


def test_hardware_detail_screen_history_fn_top_right_box_stays_empty():
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    screen = DetailScreen(buffer, "Cooling", ["line"], manager, history_fn=lambda: [1.0, 2.0])
    manager.push(screen)

    left_width = buffer.cols // 2
    right_width = buffer.cols - left_width
    top_height = buffer.rows // 2
    # only the box's true interior (excluding its own border/side characters)
    interior_text = "".join(
        buffer.get_cell(c, r).char
        for r in range(2, top_height - 1)
        for c in range(left_width + 2, left_width + right_width - 2)
    )
    assert interior_text.strip() == ""  # no label, no content -- reserved for later


def test_hardware_detail_screen_history_fn_refreshes_the_graph_on_tick():
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    values = [1.0, 2.0]

    with patch("pyglet.clock.schedule_interval"):
        screen = DetailScreen(buffer, "Cooling", ["line"], manager, refresh=lambda: ["line"],
                               history_fn=lambda: values)
        manager.push(screen)

    values.append(99.0)
    screen._tick(dt=0.0)

    assert screen._history_values == [1.0, 2.0, 99.0]


def test_hardware_detail_screen_history_fn_alone_schedules_a_tick():
    """Regression guard: a screen could pass history_fn without refresh (no
    text lines change, only the graph does) -- the tick must still get
    scheduled, not just when refresh is also given."""
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        screen = DetailScreen(buffer, "Cooling", ["line"], manager, history_fn=lambda: [1.0])
        manager.push(screen)
    mock_schedule.assert_called_once_with(screen._tick, screen._refresh_interval)


# --- DetailScreen options panel (top-right box, only with history_fn + options) ---

def make_options():
    state = {"value": 0}
    return [
        SettingOption("First", get_value=lambda: str(state["value"]),
                      on_left=lambda: state.__setitem__("value", state["value"] - 1),
                      on_right=lambda: state.__setitem__("value", state["value"] + 1)),
        SettingOption("Second", get_value=lambda: "off"),
    ], state


def test_detail_screen_without_options_keeps_the_top_right_box_empty():
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    screen = DetailScreen(buffer, "Cooling", ["line"], manager, history_fn=lambda: [1.0])
    manager.push(screen)
    full = "".join(row_text(buffer, r) for r in range(20))
    assert "Options" not in full


def test_detail_screen_with_options_shows_them_in_the_top_right_box():
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    options, _ = make_options()
    screen = DetailScreen(buffer, "Cooling", ["line"], manager, history_fn=lambda: [1.0], options=options)
    manager.push(screen)
    full = "".join(row_text(buffer, r) for r in range(20))
    assert "Options" in full
    assert "First: < 0 >" in full
    assert "Second: < off >" in full


def test_detail_screen_down_moves_the_option_selection():
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    options, _ = make_options()
    screen = DetailScreen(buffer, "Cooling", ["line"], manager, history_fn=lambda: [1.0], options=options)
    manager.push(screen)
    assert screen._options_selected == 0
    screen.handle_motion(key.MOTION_DOWN)
    assert screen._options_selected == 1
    screen.handle_motion(key.MOTION_DOWN)
    assert screen._options_selected == 0  # wraps around


def test_detail_screen_left_right_directly_change_the_selected_options_value():
    """Same interaction as SettingScreen: no Enter needed -- Left/Right acts
    directly on whatever Up/Down currently has selected."""
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    options, state = make_options()
    screen = DetailScreen(buffer, "Cooling", ["line"], manager, history_fn=lambda: [1.0], options=options)
    manager.push(screen)

    screen.handle_motion(key.MOTION_RIGHT)
    screen.handle_motion(key.MOTION_RIGHT)
    screen.handle_motion(key.MOTION_LEFT)
    assert state["value"] == 1


def test_detail_screen_left_right_act_on_whichever_option_is_currently_selected():
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    options, state = make_options()
    screen = DetailScreen(buffer, "Cooling", ["line"], manager, history_fn=lambda: [1.0], options=options)
    manager.push(screen)

    screen.handle_motion(key.MOTION_DOWN)  # select "Second", which has no on_left/on_right
    screen.handle_motion(key.MOTION_RIGHT)
    assert state["value"] == 0  # "First" untouched -- selection moved away from it

    screen.handle_motion(key.MOTION_UP)  # back to "First"
    screen.handle_motion(key.MOTION_RIGHT)
    assert state["value"] == 1


def test_detail_screen_escape_pops_the_screen():
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    options, _ = make_options()
    screen = DetailScreen(buffer, "Cooling", ["line"], manager, history_fn=lambda: [1.0], options=options)
    manager.push(screen)

    screen.handle_key(key.ESCAPE, 0)
    assert manager.active is None


def test_detail_screen_motion_and_enter_are_a_noop_without_options():
    buffer = ScreenBuffer(60, 20)
    manager = ScreenManager()
    screen = DetailScreen(buffer, "Cooling", ["line"], manager, history_fn=lambda: [1.0])
    manager.push(screen)
    screen.handle_motion(key.MOTION_DOWN)  # should not raise
    screen.handle_enter()  # should not raise


# --- box_drawing.draw_line_graph ---

def test_draw_line_graph_plots_within_a_bordered_box():
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [1.0, 5.0, 3.0])
    assert row_text(buffer, 0).startswith("+ History ")
    assert row_text(buffer, 9).startswith("+")  # bottom border present


def test_draw_line_graph_shows_the_latest_value_next_to_the_label():
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [30.0, 45.2])
    assert row_text(buffer, 0).startswith("+ History |45.2C|")  # values[-1], not the first or a random one


def test_draw_line_graph_without_any_values_shows_no_current_reading():
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [])
    top_border = row_text(buffer, 0)
    assert top_border.startswith("+ History ")
    assert top_border.rstrip("-+ ") == "+ History"  # nothing but dashes after the label


def test_draw_line_graph_higher_values_plot_higher_up():
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [0.0, 10.0])
    # right-aligned: with only 2 samples and plot_width=25, they land in the last two columns (26, 27)
    plot_rows = range(2, 8)
    low_row = next(r for r in plot_rows if buffer.get_cell(26, r).char == "*")
    high_row = next(r for r in plot_rows if buffer.get_cell(27, r).char == "*")
    assert high_row < low_row  # the later, higher value (10.0) sits above the first (0.0)


def test_draw_line_graph_flat_series_draws_a_single_middle_row():
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [5.0, 5.0, 5.0])
    rows_with_marks = {r for r in range(2, 9) for c in range(2, 28) if buffer.get_cell(c, r).char == "*"}
    assert len(rows_with_marks) == 1  # every sample lands on the same row


def test_draw_line_graph_with_no_values_shows_a_placeholder():
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [])
    assert "No data yet" in row_text(buffer, 2)


def test_draw_line_graph_only_shows_the_most_recent_window():
    """More samples than there are columns to plot them in -- only the
    latest interior_width-worth should show, not a squashed-together whole
    history."""
    buffer = ScreenBuffer(10, 10)  # interior_width = 10 - 4 = 6
    draw_line_graph(buffer, 0, 0, 10, 10, "H", [0.0] * 50 + [10.0])
    last_col_char = buffer.get_cell(7, 2).char  # x=0+2+(6-1)=7 -- the graph's last plottable column
    assert last_col_char == "*"  # the most recent sample (10.0) is the one actually shown there


def test_draw_line_graph_fills_in_from_the_right_while_the_window_is_not_yet_full():
    """Before there's enough data to fill the whole plot width, the newest
    sample must stay pinned at the fixed rightmost column -- unused columns
    sit empty on the *left*, and each further sample extends the marked
    range one column further left, not right."""
    buffer = ScreenBuffer(10, 10)  # plot_width = (10 - 4) - 1 = 5

    def marked_columns() -> set[int]:
        return {c for c in range(10) for r in range(10) if buffer.get_cell(c, r).char == "*"}

    draw_line_graph(buffer, 0, 0, 10, 10, "H", [1.0, 2.0])
    cols_after_two = marked_columns()
    assert len(cols_after_two) == 2

    draw_line_graph(buffer, 0, 0, 10, 10, "H", [1.0, 2.0, 3.0])
    cols_after_three = marked_columns()

    assert max(cols_after_three) == max(cols_after_two)  # newest still lands in the same rightmost column
    assert min(cols_after_three) == min(cols_after_two) - 1  # extends one column further left


def test_draw_line_graph_once_full_keeps_the_newest_on_the_right_and_drops_the_oldest():
    """Once there are more samples than plot columns, the window must not
    keep growing -- the same amount of columns stay marked (the oldest
    sample falls off the left), and the newest one always lands in the same
    rightmost column instead of advancing further, since there's nowhere
    further right to go."""
    buffer = ScreenBuffer(11, 10)  # plot_width = (11 - 4) - 2 = 5

    def marked_columns() -> set[int]:
        return {c for c in range(11) for r in range(10) if buffer.get_cell(c, r).char == "*"}

    draw_line_graph(buffer, 0, 0, 11, 10, "H", [1.0, 2.0, 3.0, 4.0, 5.0])  # exactly fills the window
    assert len(marked_columns()) == 5
    rightmost_when_full = max(marked_columns())

    draw_line_graph(buffer, 0, 0, 11, 10, "H", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])  # one more than fits
    columns_after = marked_columns()

    assert len(columns_after) == 5  # still capped at plot_width, not growing
    assert max(columns_after) == rightmost_when_full  # the newest sample lands in the same rightmost column


def test_draw_line_graph_shows_the_y_axis_label_and_time_on_the_x_axis():
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [1.0, 2.0], y_label="Temp")

    label_col = 2  # x + 2 -- the y-axis label's column, one letter per row
    y_axis_text = "".join(buffer.get_cell(label_col, r).char for r in range(2, 6))
    assert y_axis_text == "Temp"

    full = "".join(row_text(buffer, r) for r in range(10))
    assert "Time" in full  # the x-axis label is a normal horizontal string, unlike the y one


def test_draw_line_graph_markers_draw_labeled_reference_lines():
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [25.0, 26.0], markers=[0.0, 80.0, 90.0])
    full = "".join(row_text(buffer, r) for r in range(10))
    assert "80" in full
    assert "90" in full


def test_draw_line_graph_markers_show_even_without_any_data():
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [], markers=[0.0, 90.0])
    full = "".join(row_text(buffer, r) for r in range(10))
    assert "No data yet" not in full
    assert "90" in full


def test_draw_line_graph_markers_extend_the_scale_beyond_the_data():
    """A marker far outside the data's own range must still be visible --
    the y-axis scale stretches to include it, not just the plotted data."""
    buffer = ScreenBuffer(30, 10)
    draw_line_graph(buffer, 0, 0, 30, 10, "History", [25.0, 25.0, 25.0], markers=[0.0, 90.0])
    assert buffer.get_cell(4, 2).char == "9"  # the "90" marker line sits at the very top plot row
    assert buffer.get_cell(26, 6).char == "*"  # the flat 25.0 data sits well below it, not at the top


# --- BootScreen / LogoScreen sound hooks ---

class FakePlayer:
    """Stand-in for the pyglet.media.Player returned by fade_in()."""

    def __init__(self, loop: bool) -> None:
        self.loop = loop
        self.playing = True
        self.paused_count = 0

    def pause(self) -> None:
        self.paused_count += 1
        self.playing = False


class FakeSounds:
    """Records .play()/.fade_out()/.set_sound_volume()/.fade_in() calls
    instead of touching real audio -- keeps these tests fast and independent
    of whether an audio driver is available."""

    def __init__(self) -> None:
        self.played: list[str] = []
        self.fades: list[tuple[float, float]] = []
        self.faded_players: list = []  # the `player=` each fade_out() call was scoped to (or None)
        self.sound_volumes: dict[str, float] = {}
        self.fade_ins: list[tuple[str, float, float, bool]] = []
        self.play_players: dict[str, FakePlayer] = {}  # name -> the player returned by play()

    def play(self, name: str) -> FakePlayer:
        self.played.append(name)
        player = FakePlayer(loop=False)
        self.play_players[name] = player
        return player

    def fade_out(self, target_volume: float, duration: float, on_complete=None, player=None) -> None:
        self.fades.append((target_volume, duration))
        self.faded_players.append(player)
        if on_complete is not None:
            on_complete()

    def set_sound_volume(self, name: str, volume: float) -> None:
        self.sound_volumes[name] = volume

    def fade_in(self, name: str, target_volume: float, duration: float, loop: bool = False) -> FakePlayer:
        self.fade_ins.append((name, target_volume, duration, loop))
        return FakePlayer(loop)


def test_boot_screen_plays_tick_for_each_non_blank_line():
    buffer = ScreenBuffer(40, 10)
    sounds = FakeSounds()
    frames = [BootFrame("line one", delay=0), BootFrame("line two", delay=0)]
    screen = BootScreen(buffer, frames, on_complete=lambda: None, sounds=sounds)
    screen._advance(0.0)
    screen._advance(0.0)
    assert sounds.played.count("boot_tick") == 2


def test_boot_screen_skips_tick_for_blank_line():
    buffer = ScreenBuffer(40, 10)
    sounds = FakeSounds()
    frames = [BootFrame("", delay=0)]
    screen = BootScreen(buffer, frames, on_complete=lambda: None, sounds=sounds)
    screen._advance(0.0)
    assert "boot_tick" not in sounds.played


def test_boot_screen_plays_complete_sound_on_finish():
    buffer = ScreenBuffer(40, 10)
    sounds = FakeSounds()
    frames = [BootFrame("only line", delay=0)]
    screen = BootScreen(buffer, frames, on_complete=lambda: None, sounds=sounds)
    screen._advance(0.0)  # writes the only line
    screen._advance(0.0)  # index >= len(frames) -> finish
    assert sounds.played[-1] == "boot_complete"


def test_boot_screen_fades_out_ambient_sounds_before_the_complete_chime():
    buffer = ScreenBuffer(40, 10)
    sounds = FakeSounds()
    frames = [BootFrame("only line", delay=0)]
    screen = BootScreen(buffer, frames, on_complete=lambda: None, sounds=sounds,
                         fade_out_target=0.2, fade_out_duration=3.0)
    screen._advance(0.0)
    screen._advance(0.0)  # finish
    assert sounds.fades == [(0.2, 3.0)]


def test_boot_screen_finish_uses_default_fade_out_values():
    buffer = ScreenBuffer(40, 10)
    sounds = FakeSounds()
    screen = BootScreen(buffer, [], on_complete=lambda: None, sounds=sounds)
    screen._finish()
    assert sounds.fades == [(0.01, 2.0)]


def test_boot_screen_works_without_sounds():
    buffer = ScreenBuffer(40, 10)
    frames = [BootFrame("line", delay=0)]
    screen = BootScreen(buffer, frames, on_complete=lambda: None)  # sounds=None
    screen._advance(0.0)
    screen._finish()  # should not raise


def test_logo_screen_plays_stinger_on_push():
    buffer = ScreenBuffer(40, 10)
    sounds = FakeSounds()
    screen = LogoScreen(buffer, ["LOGO"], on_complete=lambda: None, sounds=sounds)
    screen.on_push()
    pyglet.clock.unschedule(screen._advance)
    assert sounds.played == ["logo_stinger"]


def test_logo_screen_works_without_sounds():
    buffer = ScreenBuffer(40, 10)
    screen = LogoScreen(buffer, ["LOGO"], on_complete=lambda: None)  # sounds=None
    screen.on_push()  # should not raise
    pyglet.clock.unschedule(screen._advance)


def test_logo_screen_stops_the_stinger_when_skipped():
    buffer = ScreenBuffer(40, 10)
    sounds = FakeSounds()
    screen = LogoScreen(buffer, ["LOGO"], on_complete=lambda: None, sounds=sounds)
    screen.on_push()
    player = sounds.play_players["logo_stinger"]
    assert player.playing is True

    screen.handle_key(key.A, 0)  # skip
    assert player.paused_count == 1
    assert player.playing is False


def test_logo_screen_enter_also_stops_the_stinger():
    buffer = ScreenBuffer(40, 10)
    sounds = FakeSounds()
    screen = LogoScreen(buffer, ["LOGO"], on_complete=lambda: None, sounds=sounds)
    screen.on_push()
    player = sounds.play_players["logo_stinger"]

    screen.handle_enter()  # skip
    assert player.paused_count == 1


def test_logo_screen_natural_finish_does_not_stop_the_stinger():
    """Only an explicit skip stops the sound early -- letting the logo finish
    on its own leaves the stinger playing (it's expected to run its course)."""
    buffer = ScreenBuffer(40, 10)
    sounds = FakeSounds()
    screen = LogoScreen(buffer, ["x"], on_complete=lambda: None, sounds=sounds)
    screen.on_push()
    player = sounds.play_players["logo_stinger"]

    screen._advance(0.0)  # writes the only line
    screen._advance(0.0)  # index >= len(lines) -> natural _finish()
    assert player.paused_count == 0


# --- BootScreen / LogoScreen: only one input channel skips (regression) ---
#
# pyglet dispatches on_key_press for virtually every key -- including ones
# that also produce on_text (e.g. letters, space) or on_text_motion (e.g.
# arrows). If handle_text/handle_motion ALSO called _finish(), a single
# physical keystroke would fire it twice: once via handle_text/handle_motion,
# and again via handle_key once the screen manager's active screen has
# already moved on -- skipping straight through two screens (e.g. Boot and
# Logo) instead of stopping at the first one.

def test_boot_screen_handle_text_does_not_skip():
    buffer = ScreenBuffer(40, 10)
    finished = []
    screen = BootScreen(buffer, [BootFrame("x", delay=0)], on_complete=lambda: finished.append(True))
    screen.handle_text("a")
    assert finished == []


def test_boot_screen_handle_motion_does_not_skip():
    buffer = ScreenBuffer(40, 10)
    finished = []
    screen = BootScreen(buffer, [BootFrame("x", delay=0)], on_complete=lambda: finished.append(True))
    screen.handle_motion(key.MOTION_LEFT)
    assert finished == []


def test_boot_screen_handle_key_still_skips():
    buffer = ScreenBuffer(40, 10)
    finished = []
    screen = BootScreen(buffer, [BootFrame("x", delay=0)], on_complete=lambda: finished.append(True))
    screen.handle_key(key.A, 0)
    assert finished == [True]


def test_boot_screen_handle_enter_still_skips():
    buffer = ScreenBuffer(40, 10)
    finished = []
    screen = BootScreen(buffer, [BootFrame("x", delay=0)], on_complete=lambda: finished.append(True))
    screen.handle_enter()
    assert finished == [True]


def test_logo_screen_handle_text_does_not_skip():
    buffer = ScreenBuffer(40, 10)
    finished = []
    screen = LogoScreen(buffer, ["LOGO"], on_complete=lambda: finished.append(True))
    screen.handle_text("a")
    assert finished == []


def test_logo_screen_handle_motion_does_not_skip():
    buffer = ScreenBuffer(40, 10)
    finished = []
    screen = LogoScreen(buffer, ["LOGO"], on_complete=lambda: finished.append(True))
    screen.handle_motion(key.MOTION_LEFT)
    assert finished == []


def test_logo_screen_handle_key_still_skips():
    buffer = ScreenBuffer(40, 10)
    finished = []
    screen = LogoScreen(buffer, ["LOGO"], on_complete=lambda: finished.append(True))
    screen.handle_key(key.A, 0)
    assert finished == [True]


def test_one_keystroke_skips_boot_but_not_also_logo():
    """End-to-end regression test for the reported bug: pressing a single key
    while Boot is showing must land on Logo, not cascade straight through to
    whatever comes after Logo. A real keystroke that produces text dispatches
    on_text AND on_key_press for the SAME press -- reproduced here by calling
    handle_text then handle_key in that order, matching pyglet's real order."""
    buffer = ScreenBuffer(40, 10)
    manager = ScreenManager()
    after_logo = []

    def on_logo_complete():
        after_logo.append(True)

    def on_boot_complete():
        manager.pop()
        manager.push(LogoScreen(buffer, ["LOGO"], on_complete=on_logo_complete))

    boot = BootScreen(buffer, [BootFrame("x", delay=0)], on_complete=on_boot_complete)
    manager.push(boot)

    # one physical keystroke: pyglet fires on_text first, then on_key_press
    manager.handle_text("a")
    manager.handle_key(key.A, 0)

    assert isinstance(manager.active, LogoScreen)
    assert after_logo == []  # must NOT have also skipped Logo in the same keystroke

    # a second, separate keystroke should now finish Logo
    manager.handle_text("a")
    manager.handle_key(key.A, 0)
    assert after_logo == [True]
