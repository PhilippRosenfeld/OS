from unittest.mock import patch

import pyglet
import pytest

from horus.apps.shell_window import ShellWindow
from horus.apps.window import Window
from horus.apps.window_manager import WindowManager, is_switch_key, show_app, show_window
from horus.display.colors import NAMED_COLORS
from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.kernel.kernel import Kernel
from horus.kernel.registry import Registry, command
from horus.processes.processTable import ProcessTable
from horus.session.context import Context
from horus.session.history import CommandHistory
from horus.session.user import UserRole
from horus.shell.input_handler import InputHandler
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.menu_screen import MenuScreen
from horus.ui.screens.shell_screen import ShellScreen

key = pyglet.window.key
CTRL_ALT = (key.LALT, key.MOD_CTRL)


def row_text(buffer, row):
    return "".join(buffer.get_cell(c, row).char for c in range(buffer.cols))


def full_text(buffer):
    return "\n".join(row_text(buffer, r) for r in range(buffer.rows))


@pytest.fixture(autouse=True)
def no_clock():
    with patch("pyglet.clock.schedule_interval"), patch("pyglet.clock.unschedule"):
        yield


def make_commands():
    commands = Registry()

    @command("greet", help_text="Say hello", target=commands)
    def greet(ctx, argv):
        ctx.write_line(f"hello {' '.join(argv) or 'world'}")

    @command("spam", help_text="Print many lines", target=commands)
    def spam(ctx, argv):
        for i in range(int(argv[0])):
            ctx.write_line(f"line {i}")

    @command("ask", help_text="Ask a question", target=commands)
    def ask(ctx, argv):
        ctx.write_line("name?")
        ctx.request_input(lambda answer: ctx.write_line(f"hi {answer}"))

    @command("set", help_text="Remember a setting", target=commands)
    def set_(ctx, argv):
        ctx.env[argv[0]] = argv[1]

    @command("get", help_text="Show a setting", target=commands)
    def get(ctx, argv):
        ctx.write_line(f"{argv[0]}={ctx.env.get(argv[0], '')}")

    return commands


class Desktop:
    """The main shell (a real ShellScreen on the main buffer) with a
    process table and event bus -- what windows open over in the game."""

    def __init__(self, cols=80, rows=24):
        self.buffer = ScreenBuffer(cols, rows)
        self.screens = ScreenManager()
        self.bus = EventBus()
        self.table = ProcessTable(events=self.bus)
        self.ctx = Context(session_id="s", user="root", cwd="/", screen=self.buffer, screens=self.screens,
                           events=self.bus, process_table=self.table)
        self.shell_commands = Registry()
        kernel = Kernel(registry=self.shell_commands, bus=self.bus)
        self.input = InputHandler(self.buffer, CommandHistory(), on_submit=lambda line: kernel.execute(line, self.ctx),
                                  get_prompt=lambda: "$ ")
        self.ctx.input_handler = self.input
        self.shell = ShellScreen(self.input, self.screens)
        self.screens.push(self.shell)

        @command("echo", help_text="", target=self.shell_commands)
        def echo(ctx, argv):
            ctx.write_line(" ".join(argv))

    def open(self, title="Test App", window_class=ShellWindow, **kwargs):
        if window_class is ShellWindow or issubclass(window_class, ShellWindow):
            kwargs.setdefault("commands", make_commands())
        window = window_class(self.ctx, title, **kwargs)
        manager = show_window(self.ctx, window)
        return window, manager


def type_line(manager, line):
    manager.handle_text(line)
    manager.handle_enter()


def shell_text(window, manager):
    """The window's shell area as it appears on the composited display."""
    left, top = manager.position_of(window)
    x, y, width, height = window.content_rect
    return [row_text(manager.display, top + y + r)[left + x:left + x + width].rstrip() for r in range(height)]


# --- placement and compositing ---

def test_opens_a_centered_framed_window_over_the_shell():
    desk = Desktop()
    window, manager = desk.open(width=40, height=12)
    assert isinstance(desk.screens.active, WindowManager) and manager.base is desk.shell
    assert row_text(manager.display, 6)[20:].startswith("+ Test App ")     # (80-40)//2, (24-12)//2
    assert row_text(manager.display, 17)[20:60] == "+" + "-" * 38 + "+"
    assert row_text(manager.display, 0).startswith("$")                    # the shell around it
    assert shell_text(window, manager)[0] == ">"


def test_windows_never_draw_into_the_shells_own_buffer():
    desk = Desktop()
    before = full_text(desk.buffer)
    window, manager = desk.open()
    type_line(manager, "spam 30")
    assert full_text(desk.buffer) == before


def test_window_defaults_to_three_quarters_of_the_screen():
    desk = Desktop()
    window, manager = desk.open()
    assert window.size == (60, 18) and manager.position_of(window) == (10, 3)


def test_further_windows_cascade():
    desk = Desktop()
    first, manager = desk.open("One", width=40, height=12)
    second, _ = desk.open("Two", width=40, height=12)
    assert manager.position_of(first) == (20, 6)
    assert manager.position_of(second) == (22, 7)


def test_the_cursor_sits_after_the_prompt_inside_the_focused_window():
    desk = Desktop()
    window, manager = desk.open(width=40, height=12)
    manager.handle_text("ab")
    left, top = manager.position_of(window)
    x, y, _, _ = window.content_rect
    assert (manager.display.cursor_col, manager.display.cursor_row) == (left + x + 4, top + y)    # "> ab"
    assert manager.display.cursor_enabled


def test_the_focused_window_shows_its_title_inverted():
    desk = Desktop()
    window, manager = desk.open(width=40, height=12)
    assert manager.display.get_cell(22, 6).char == "T"
    assert manager.display.get_cell(22, 6).bg_color == manager.display.default_fg


def test_a_grid_size_change_refits_the_windows():
    desk = Desktop()
    window, manager = desk.open()
    desk.buffer.resize(100, 30)
    manager._tick(0.1)
    assert window.size == (75, 22) and manager.position_of(window) == (12, 4)
    assert (manager.display.cols, manager.display.rows) == (100, 30)
    assert row_text(manager.display, 4)[12:].startswith("+ Test App ")


# --- switching the focus with Ctrl+Alt ---

def test_ctrl_alt_cycles_the_focus_through_shell_and_windows():
    desk = Desktop()
    one, manager = desk.open("One", width=40, height=12)
    two, _ = desk.open("Two", width=40, height=12)
    assert manager.focused is two
    manager.handle_key(*CTRL_ALT)
    assert manager.focused is None                    # the shell
    manager.handle_key(*CTRL_ALT)
    assert manager.focused is one and one.focused and not two.focused
    manager.handle_key(*CTRL_ALT)
    assert manager.focused is two


def test_ctrl_alt_shift_cycles_backwards():
    desk = Desktop()
    one, manager = desk.open("One")
    two, _ = desk.open("Two")
    manager.handle_key(key.LALT, key.MOD_CTRL | key.MOD_SHIFT)
    assert manager.focused is one


def test_switching_works_with_either_key_pressed_last():
    assert is_switch_key(key.LALT, key.MOD_CTRL)
    assert is_switch_key(key.LCTRL, key.MOD_ALT)
    assert is_switch_key(key.RCTRL, key.MOD_ALT)
    assert not is_switch_key(key.LALT, 0)
    assert not is_switch_key(key.A, key.MOD_CTRL | key.MOD_ALT)


def test_altgr_does_not_switch_windows():
    """On Windows AltGr arrives as Ctrl (no Alt yet), then right Alt with Ctrl held."""
    desk = Desktop()
    window, manager = desk.open()
    manager.handle_key(key.LCTRL, 0)
    manager.handle_key(key.RALT, key.MOD_CTRL)
    assert manager.focused is window


def test_the_focused_window_gets_the_input_and_comes_to_the_front():
    desk = Desktop()
    one, manager = desk.open("One", width=40, height=12)
    two, _ = desk.open("Two", width=40, height=12)
    manager.focus(one)
    type_line(manager, "greet one")
    assert "hello one" in shell_text(one, manager)
    assert "hello one" not in full_text(two.surface)
    assert row_text(manager.display, 6)[20:].startswith("+ One ")   # drawn over Two's overlapping frame


def test_focusing_the_shell_shows_it_unobstructed_and_gives_it_the_input():
    desk = Desktop()
    window, manager = desk.open()
    manager.handle_key(*CTRL_ALT)
    assert "Test App" not in full_text(manager.display)
    type_line(manager, "echo hi")
    assert "hi" in full_text(desk.buffer)
    assert row_text(manager.display, desk.buffer.cursor_row).startswith("$")
    assert manager.display.cursor_row == desk.buffer.cursor_row


def test_the_shell_gets_the_prompt_it_owes_when_focused():
    """Opening a window from the shell left its prompt pending."""
    desk = Desktop()

    @command("open", help_text="", target=desk.shell_commands)
    def open_(ctx, argv):
        show_window(ctx, ShellWindow(ctx, "Opened", commands=make_commands()))

    type_line(desk.screens, "open")
    manager = desk.screens.active
    assert isinstance(manager, WindowManager)
    prompts = full_text(desk.buffer).count("$")
    manager.handle_key(*CTRL_ALT)
    assert full_text(desk.buffer).count("$") == prompts + 1


def test_unfocused_windows_keep_updating():
    class Clock(Window):
        ticks = 0

        def update(self, dt):
            self.ticks += 1
            super().update(dt)

        def render_content(self, x, y, width, height):
            self.write(x, y, f"ticks: {self.ticks}")

    desk = Desktop()
    clock, manager = desk.open("Clock", window_class=Clock, width=30, height=8)
    manager.handle_key(*CTRL_ALT)        # focus the shell
    for _ in range(3):
        manager._tick(0.1)
    assert clock.ticks == 3 and "ticks: 3" in full_text(clock.surface)
    manager.handle_key(*CTRL_ALT)
    assert "ticks: 3" in full_text(manager.display)


# --- shell inside a window ---

def test_commands_run_and_print_inside_the_window():
    desk = Desktop()
    window, manager = desk.open(width=40, height=12)
    type_line(manager, "greet you")
    assert shell_text(window, manager)[:3] == ["> greet you", "hello you", ">"]


def test_the_main_shells_commands_are_not_available():
    desk = Desktop()
    window, manager = desk.open()
    type_line(manager, "echo")
    assert "echo: Command not found" in shell_text(window, manager)


def test_long_output_scrolls_inside_the_window_and_leaves_the_frame_alone():
    desk = Desktop()
    window, manager = desk.open(width=40, height=12)
    type_line(manager, "spam 30")
    lines = shell_text(window, manager)
    assert lines[-1] == ">" and lines[-2] == "line 29"
    assert row_text(manager.display, 6)[20:].startswith("+ Test App ")


def test_help_lists_program_and_built_in_commands():
    desk = Desktop()
    window, manager = desk.open()
    type_line(manager, "help")
    text = "\n".join(shell_text(window, manager))
    for name in ("greet", "spam", "help", "clear", "exit"):
        assert name in text
    assert "quit" not in text                         # only for programs that keep running


def test_a_program_can_override_a_built_in():
    commands = make_commands()

    @command("help", help_text="custom", target=commands)
    def my_help(ctx, argv):
        ctx.write_line("custom help")

    desk = Desktop()
    window, manager = desk.open(commands=commands)
    type_line(manager, "help")
    assert "custom help" in shell_text(window, manager)


def test_clear_empties_the_window():
    desk = Desktop()
    window, manager = desk.open()
    type_line(manager, "greet")
    type_line(manager, "clear")
    lines = shell_text(window, manager)
    assert lines[0] == ">" and all(line == "" for line in lines[1:])


def test_history_is_the_windows_own():
    desk = Desktop()
    window, manager = desk.open()
    type_line(manager, "greet a")
    manager.handle_motion(key.MOTION_UP)
    assert window.input.current_line == "greet a"


def test_request_input_prompts_inside_the_window():
    desk = Desktop()
    window, manager = desk.open()
    type_line(manager, "ask")
    type_line(manager, "bob")
    assert "hi bob" in shell_text(window, manager)


def test_tab_completes_command_names():
    desk = Desktop()
    window, _ = desk.open()
    assert window.complete("gr") == ["greet"]


def test_a_custom_prompt_is_used():
    class Prompted(ShellWindow):
        def prompt(self):
            return "net> "

    desk = Desktop()
    window, manager = desk.open(window_class=Prompted)
    assert shell_text(window, manager)[0] == "net>"


def test_welcome_lines_come_before_the_first_prompt():
    desk = Desktop()
    window, manager = desk.open(welcome=["Welcome!", ""])
    assert shell_text(window, manager)[:3] == ["Welcome!", "", ">"]


def test_header_rows_are_drawn_above_a_rule_and_refreshed():
    class WithHeader(ShellWindow):
        status = "LINK UP"

        def render_header(self):
            self.header_write(0, 0, self.status)

    desk = Desktop()
    window, manager = desk.open(window_class=WithHeader, width=40, height=12, header_rows=1)
    assert row_text(manager.display, 7)[22:].startswith("LINK UP")
    assert row_text(manager.display, 8)[20:60] == "+" + "-" * 38 + "+"
    assert window.content_rect[1] == 3
    window.status = "DOWN"
    manager._tick(0.1)
    assert row_text(manager.display, 7)[22:30] == "DOWN    "


def test_a_full_screen_opened_by_a_window_command_returns_to_a_fresh_prompt():
    commands = make_commands()

    @command("menu", help_text="Open a menu", target=commands)
    def menu(ctx, argv):
        ctx.screens.push(MenuScreen(ctx.screens.active.main_buffer, "Sub", [], ctx.screens))

    desk = Desktop()
    window, manager = desk.open(commands=commands)
    type_line(manager, "menu")
    assert desk.screens.active is not manager
    desk.screens.pop()
    assert desk.screens.active is manager
    assert shell_text(window, manager)[1] == ">"


# --- closing ---

def test_exit_closes_the_last_window_and_returns_to_the_shell():
    desk = Desktop()
    window, manager = desk.open()
    type_line(manager, "exit")
    assert desk.screens.active is desk.shell
    assert not window.is_open


def test_closing_one_of_several_windows_moves_the_focus_on():
    desk = Desktop()
    one, manager = desk.open("One")
    two, _ = desk.open("Two")
    type_line(manager, "exit")
    assert manager.focused is one and desk.screens.active is manager
    assert manager.windows == [one]


def test_escape_closes_the_window():
    desk = Desktop()
    window, manager = desk.open()
    manager.handle_key(key.ESCAPE, 0)
    assert desk.screens.active is desk.shell


def test_close_keys_are_configurable():
    desk = Desktop()
    window, manager = desk.open(close_keys=())
    manager.handle_key(key.ESCAPE, 0)
    assert desk.screens.active is manager and window.is_open


# --- process ---

def test_the_program_runs_as_a_process_while_open():
    desk = Desktop()
    window, manager = desk.open(process_name="testapp")
    proc = desk.table.get_process(window.pid)
    assert proc.name == "testapp" and proc.owner == "root"
    type_line(manager, "exit")
    assert desk.table.list_processes() == []


def test_killing_the_process_closes_its_window():
    desk = Desktop()
    window, manager = desk.open(process_name="testapp")
    desk.table.remove_process(window.pid, user="root", role=UserRole.ROOT)
    assert desk.screens.active is desk.shell
    assert not window.is_open


def test_process_load_can_change_while_open():
    desk = Desktop()
    window, _ = desk.open(process_name="testapp")
    window.set_process_load(cpu_mhz=250, mem_kb=8192)
    proc = desk.table.get_process(window.pid)
    assert (proc.cpu_mhz, proc.baseline_cpu_mhz, proc.mem_kb) == (250, 250, 8192)


# --- programs running on in the background ---

def open_app(desk, **kwargs):
    kwargs.setdefault("commands", make_commands())
    return show_app(desk.ctx, "bgapp", lambda: ShellWindow(desk.ctx, "Background App", process_name="bgapp",
                                                           keep_running=True, **kwargs))


def test_exit_hides_a_background_program_but_keeps_its_process():
    desk = Desktop()
    manager = open_app(desk)
    window = manager.focused
    type_line(manager, "exit")
    assert desk.screens.active is desk.shell
    assert window.is_open and not window.attached
    assert desk.table.get_process(window.pid).name == "bgapp"
    assert desk.ctx.background_apps["bgapp"] is window


def test_reopening_brings_back_the_same_window_with_its_shell_history_and_settings():
    desk = Desktop()
    manager = open_app(desk)
    window = manager.focused
    pid = window.pid
    type_line(manager, "greet before")
    type_line(manager, "set mode turbo")
    type_line(manager, "exit")

    manager = open_app(desk)
    assert manager.focused is window and window.pid == pid
    assert "hello before" in shell_text(window, manager)        # output still there
    type_line(manager, "get mode")
    assert "mode=turbo" in shell_text(window, manager)          # setting kept
    manager.handle_motion(key.MOTION_UP)
    assert window.input.current_line == "get mode"              # history kept
    assert len(desk.table.list_processes()) == 1                # still the one process


def test_a_hidden_program_gets_its_prompt_back_when_reopened():
    desk = Desktop()
    manager = open_app(desk)
    window = manager.focused
    type_line(manager, "exit")
    manager = open_app(desk)
    assert shell_text(window, manager)[1] == ">"                 # prompt after the 'exit' line


def test_quit_ends_a_background_program():
    desk = Desktop()
    manager = open_app(desk)
    window = manager.focused
    type_line(manager, "help")
    assert "quit" in "\n".join(shell_text(window, manager))
    type_line(manager, "quit")
    assert not window.is_open
    assert desk.table.list_processes() == [] and "bgapp" not in desk.ctx.background_apps
    assert open_app(desk).focused is not window                 # starts fresh next time


def test_escape_hides_a_background_program_too():
    desk = Desktop()
    manager = open_app(desk)
    window = manager.focused
    manager.handle_key(key.ESCAPE, 0)
    assert window.is_open and not window.attached


def test_killing_a_hidden_programs_process_ends_it():
    desk = Desktop()
    manager = open_app(desk)
    window = manager.focused
    type_line(manager, "exit")
    desk.table.remove_process(window.pid, user="root", role=UserRole.ROOT)
    assert not window.is_open and "bgapp" not in desk.ctx.background_apps


def test_opening_an_already_shown_program_just_focuses_it():
    desk = Desktop()
    manager = open_app(desk)
    window = manager.focused
    manager.handle_key(*CTRL_ALT)
    assert manager.focused is None
    assert open_app(desk).focused is window and manager.windows == [window]


# --- plain Window (no shell) ---

def test_a_window_without_a_shell_draws_its_own_content_and_has_no_cursor():
    class Label(Window):
        def render_content(self, x, y, width, height):
            self.write(x, y, "just text")

    desk = Desktop()
    window, manager = desk.open("Label", window_class=Label, width=30, height=8,
                                border_color=NAMED_COLORS["amber"])
    left, top = manager.position_of(window)
    assert row_text(manager.display, top + 1)[left + 2:].startswith("just text")
    assert not manager.display.cursor_enabled
    assert manager.display.get_cell(left, top).fg_color == NAMED_COLORS["amber"]


# --- logging ---

def test_the_log_names_the_window_a_command_was_entered_in(caplog):
    desk = Desktop()
    window, manager = desk.open(process_name="testapp")
    with caplog.at_level("INFO", logger="horus.kernel.kernel"):
        type_line(manager, "greet")
    assert f"WINDOW=Test App (PID {window.pid})" in caplog.text


def test_a_window_without_a_process_is_logged_by_its_title(caplog):
    desk = Desktop()
    window, manager = desk.open()
    with caplog.at_level("INFO", logger="horus.kernel.kernel"):
        type_line(manager, "greet")
    assert "WINDOW=Test App," in caplog.text


def test_the_main_shell_is_logged_as_shell(caplog):
    desk = Desktop()
    with caplog.at_level("INFO", logger="horus.kernel.kernel"):
        type_line(desk.screens, "echo hi")
    assert "WINDOW=shell," in caplog.text


# --- registry target ---

def test_command_decorator_registers_into_a_given_registry_only():
    own = Registry()

    @command("only_here_xyz", help_text="x", target=own)
    def handler(ctx, argv):
        pass

    from horus.kernel.registry import registry as global_registry
    assert own.lookup("only_here_xyz") is handler
    assert global_registry.lookup("only_here_xyz") is None
