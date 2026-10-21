from unittest.mock import patch

import pyglet
import pytest

from horus.apps.shell_window import ShellWindow
from horus.apps.window import Window
from horus.apps.window_screen import WindowScreen, show_window
from horus.display.colors import NAMED_COLORS
from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.kernel.registry import Registry, command
from horus.processes.processTable import ProcessTable
from horus.session.context import Context
from horus.session.user import UserRole
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.menu_screen import MenuScreen

key = pyglet.window.key


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

    return commands


def make_ctx(cols=80, rows=24):
    buffer = ScreenBuffer(cols, rows)
    buffer.write_string(0, 0, "MAIN SHELL CONTENT")
    screens = ScreenManager()
    bus = EventBus()
    table = ProcessTable(events=bus)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, screens=screens, events=bus, process_table=table)
    return ctx, buffer, screens, table


def open_shell(cols=80, rows=24, window_class=ShellWindow, **kwargs):
    ctx, buffer, screens, table = make_ctx(cols, rows)
    kwargs.setdefault("commands", make_commands())
    window = window_class(ctx, "Test App", **kwargs)
    host = show_window(ctx, window)
    return window, host, buffer, screens, table


def type_line(window, host, line):
    host.handle_text(line)
    host.handle_enter()


def shell_text(window, host):
    """The shell's content area as it appears on the main screen."""
    left, top = host._position
    x, y, width, height = window.content_rect
    return [row_text(host.main_buffer, top + y + r)[left + x:left + x + width].rstrip() for r in range(height)]


# --- WindowScreen: placement and compositing ---

def test_opens_a_centered_framed_window_over_the_previous_screen():
    window, host, buffer, *_ = open_shell(width=40, height=12)
    assert row_text(buffer, 6)[20:].startswith("+ Test App ")     # (80-40)//2, (24-12)//2
    assert row_text(buffer, 17)[20:60] == "+" + "-" * 38 + "+"
    assert row_text(buffer, 0).startswith("MAIN SHELL CONTENT")   # still visible around the window
    assert shell_text(window, host)[0] == ">"


def test_window_defaults_to_three_quarters_of_the_screen():
    window, host, *_ = open_shell()
    assert window.size == (60, 18) and host._position == (10, 3)


def test_the_cursor_sits_after_the_prompt_inside_the_window():
    window, host, buffer, *_ = open_shell(width=40, height=12)
    host.handle_text("ab")
    left, top = host._position
    x, y, _, _ = window.content_rect
    assert (buffer.cursor_col, buffer.cursor_row) == (left + x + 4, top + y)    # "> ab"
    assert buffer.cursor_enabled


def test_the_focused_window_shows_its_title_inverted():
    window, host, buffer, *_ = open_shell(width=40, height=12)
    title_cell = buffer.get_cell(22, 6)   # 'T' of " Test App "
    assert title_cell.char == "T" and title_cell.bg_color == buffer.default_fg
    window.blur()
    host._composite()
    assert buffer.get_cell(22, 6).bg_color == buffer.default_bg


def test_a_grid_size_change_refits_the_window():
    window, host, buffer, screens, _ = open_shell()
    buffer.resize(100, 30)
    host._tick(0.1)
    assert window.size == (75, 22) and host._position == (12, 4)
    assert row_text(buffer, 4)[12:].startswith("+ Test App ")
    assert shell_text(window, host)[0] == ">"


# --- shell ---

def test_commands_run_and_print_inside_the_window():
    window, host, buffer, *_ = open_shell(width=40, height=12)
    type_line(window, host, "greet you")
    assert shell_text(window, host)[:3] == ["> greet you", "hello you", ">"]
    assert "hello you" not in row_text(buffer, 1)


def test_the_main_shells_commands_are_not_available():
    window, host, *_ = open_shell()
    type_line(window, host, "ls")
    assert "ls: Command not found" in shell_text(window, host)


def test_long_output_scrolls_inside_the_window_and_leaves_the_frame_alone():
    window, host, buffer, *_ = open_shell(width=40, height=12)
    type_line(window, host, "spam 30")
    lines = shell_text(window, host)
    assert lines[-1] == ">" and lines[-2] == "line 29"
    assert row_text(buffer, 6)[20:].startswith("+ Test App ")
    assert row_text(buffer, 0).startswith("MAIN SHELL CONTENT")


def test_help_lists_program_and_built_in_commands():
    window, host, *_ = open_shell()
    type_line(window, host, "help")
    text = "\n".join(shell_text(window, host))
    for name in ("greet", "spam", "help", "clear", "exit"):
        assert name in text
    assert "Say hello" in text


def test_a_program_can_override_a_built_in():
    commands = make_commands()

    @command("help", help_text="custom", target=commands)
    def my_help(ctx, argv):
        ctx.write_line("custom help")

    window, host, *_ = open_shell(commands=commands)
    type_line(window, host, "help")
    assert "custom help" in shell_text(window, host)


def test_clear_empties_the_window():
    window, host, *_ = open_shell()
    type_line(window, host, "greet")
    type_line(window, host, "clear")
    lines = shell_text(window, host)
    assert lines[0] == ">" and all(line == "" for line in lines[1:])


def test_history_is_the_windows_own():
    window, host, *_ = open_shell()
    type_line(window, host, "greet a")
    host.handle_motion(key.MOTION_UP)
    assert window.input.current_line == "greet a"


def test_request_input_prompts_inside_the_window():
    window, host, *_ = open_shell()
    type_line(window, host, "ask")
    type_line(window, host, "bob")
    assert "hi bob" in shell_text(window, host)


def test_tab_completes_command_names():
    window, *_ = open_shell()
    assert window.complete("gr") == ["greet"]


def test_a_custom_prompt_is_used():
    class Prompted(ShellWindow):
        def prompt(self):
            return "net> "

    window, host, *_ = open_shell(window_class=Prompted)
    assert shell_text(window, host)[0] == "net>"


def test_welcome_lines_come_before_the_first_prompt():
    window, host, *_ = open_shell(welcome=["Welcome!", ""])
    assert shell_text(window, host)[:3] == ["Welcome!", "", ">"]


def test_header_rows_are_drawn_above_a_rule_and_refreshed():
    class WithHeader(ShellWindow):
        status = "LINK UP"

        def render_header(self):
            self.header_write(0, 0, self.status)

    window, host, buffer, *_ = open_shell(window_class=WithHeader, width=40, height=12, header_rows=1)
    assert row_text(buffer, 7)[22:].startswith("LINK UP")
    assert row_text(buffer, 8)[20:60] == "+" + "-" * 38 + "+"
    assert window.content_rect[1] == 3

    window.status = "DOWN"
    host._tick(0.1)
    assert row_text(buffer, 7)[22:30] == "DOWN    "


def test_a_screen_opened_by_a_command_returns_to_a_fresh_prompt():
    commands = make_commands()

    @command("menu", help_text="Open a menu", target=commands)
    def menu(ctx, argv):
        ctx.screens.push(MenuScreen(ctx.screens.active.main_buffer, "Sub", [], ctx.screens))

    window, host, buffer, screens, _ = open_shell(commands=commands)
    type_line(window, host, "menu")
    assert screens.active is not host
    screens.pop()
    assert screens.active is host
    assert shell_text(window, host)[1] == ">"


# --- closing ---

def test_exit_closes_the_window_and_restores_the_screen_underneath():
    window, host, buffer, screens, _ = open_shell()
    type_line(window, host, "exit")
    assert screens.active is None
    assert not window.is_open
    assert row_text(buffer, 0).startswith("MAIN SHELL CONTENT")
    assert "Test App" not in full_text(buffer)


def test_escape_closes_the_window():
    window, host, buffer, screens, _ = open_shell()
    host.handle_key(key.ESCAPE, 0)
    assert screens.active is None


def test_close_keys_are_configurable():
    window, host, buffer, screens, _ = open_shell(close_keys=())
    host.handle_key(key.ESCAPE, 0)
    assert screens.active is host and window.is_open


# --- process ---

def test_the_program_runs_as_a_process_while_open():
    window, host, buffer, screens, table = open_shell(process_name="testapp")
    proc = table.get_process(window.pid)
    assert proc.name == "testapp" and proc.owner == "root"
    type_line(window, host, "exit")
    assert table.list_processes() == []


def test_killing_the_process_closes_the_window():
    window, host, buffer, screens, table = open_shell(process_name="testapp")
    table.remove_process(window.pid, user="root", role=UserRole.ROOT)
    assert screens.active is None
    assert not window.is_open


def test_process_load_can_change_while_open():
    window, host, buffer, screens, table = open_shell(process_name="testapp")
    window.set_process_load(cpu_mhz=250, mem_kb=8192)
    proc = table.get_process(window.pid)
    assert (proc.cpu_mhz, proc.baseline_cpu_mhz, proc.mem_kb) == (250, 250, 8192)


def test_without_a_process_name_no_process_is_started():
    window, host, buffer, screens, table = open_shell()
    assert table.list_processes() == [] and window.pid is None


# --- plain Window (no shell) ---

class Clock(Window):
    ticks = 0

    def update(self, dt):
        self.ticks += 1
        super().update(dt)

    def render_content(self, x, y, width, height):
        self.write(x, y, f"ticks: {self.ticks}")


def test_a_window_without_a_shell_draws_its_own_content_and_has_no_cursor():
    ctx, buffer, screens, _ = make_ctx()
    window = Clock(ctx, "Clock", width=30, height=8, border_color=NAMED_COLORS["amber"])
    host = show_window(ctx, window)
    host._tick(0.1)
    left, top = host._position
    assert row_text(buffer, top + 1)[left + 2:].startswith("ticks: 1")
    assert not buffer.cursor_enabled
    assert buffer.get_cell(left, top).fg_color == NAMED_COLORS["amber"]   # colored frame


class FakeHost:
    """A minimal stand-in for a future window manager: no screen stack
    juggling, just the host interface."""

    def __init__(self, screens, main_buffer):
        self.screens = screens
        self.main_buffer = main_buffer
        self.closed = []

    def is_active(self, window):
        return True

    def close_window(self, window):
        self.closed.append(window)
        window.closed()


def test_windows_only_draw_into_their_own_surface_and_run_side_by_side():
    ctx, buffer, screens, table = make_ctx()
    before = full_text(buffer)
    host = FakeHost(screens, buffer)
    shell = ShellWindow(ctx, "Shell", commands=make_commands(), process_name="a")
    clock = Clock(ctx, "Clock", process_name="b")
    shell.open(host, 40, 12)
    clock.open(host, 30, 8)
    shell.focus()

    shell.handle_text("greet")
    shell.handle_enter()
    for _ in range(3):
        shell.update(0.1)
        clock.update(0.1)    # updates although it doesn't have the focus

    assert full_text(buffer) == before                       # nothing touched the main screen
    assert "hello world" in full_text(shell.surface)
    assert "ticks: 3" in full_text(clock.surface)
    assert shell.focused and not clock.focused
    assert {proc.name for proc in table.list_processes()} == {"a", "b"}

    shell.handle_text("exit")
    shell.handle_enter()
    assert host.closed == [shell] and not shell.is_open and clock.is_open
    assert {proc.name for proc in table.list_processes()} == {"b"}


def test_show_window_pushes_a_window_screen():
    ctx, buffer, screens, _ = make_ctx()
    host = show_window(ctx, Clock(ctx, "Clock"))
    assert isinstance(screens.active, WindowScreen) and screens.active is host


# --- registry target ---

def test_command_decorator_registers_into_a_given_registry_only():
    own = Registry()

    @command("only_here_xyz", help_text="x", target=own)
    def handler(ctx, argv):
        pass

    from horus.kernel.registry import registry as global_registry
    assert own.lookup("only_here_xyz") is handler
    assert global_registry.lookup("only_here_xyz") is None
