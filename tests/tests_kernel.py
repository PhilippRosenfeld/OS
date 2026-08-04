import pytest

from horus.display.screen_buffer import ScreenBuffer
from horus.session.context import Context
from horus.events.bus import EventBus
from horus.events.types import CommandExecutedEvent
from horus.kernel.kernel import Kernel
from horus.kernel.registry import Registry, registry
from horus.kernel.commands.cmd_text import echo
from horus.kernel.commands.cmd_misc import color
from horus.display.colors import NAMED_COLORS


def make_context(cols=20, rows=5):
    buffer = ScreenBuffer(cols, rows)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer)
    return ctx, buffer


def row_text(buffer, row):
    return "".join(buffer.get_cell(c, row).char for c in range(buffer.cols))


def full_text(buffer):
    """Join every row into one string, so assertions don't break if a message happens to wrap."""
    return "".join(row_text(buffer, r) for r in range(buffer.rows))


# --- Registry ---

def test_registry_register_and_lookup():
    reg = Registry()
    handler = lambda ctx, argv: None
    reg.register("foo", handler, help_text="does foo")
    assert reg.lookup("foo") is handler
    assert reg.names() == ["foo"]
    assert reg.help_text("foo") == "does foo"


def test_registry_lookup_unknown_returns_none():
    reg = Registry()
    assert reg.lookup("missing") is None


def test_registry_lookup_none_name_returns_none():
    reg = Registry()
    assert reg.lookup(None) is None


def test_registry_register_without_name_or_handler_raises():
    reg = Registry()
    with pytest.raises(ValueError):
        reg.register("", lambda ctx, argv: None)
    with pytest.raises(ValueError):
        reg.register("foo", None)


def test_registry_register_duplicate_name_raises():
    reg = Registry()
    reg.register("foo", lambda ctx, argv: None)
    with pytest.raises(ValueError):
        reg.register("foo", lambda ctx, argv: None)


def test_registry_unregister_removes_command():
    reg = Registry()
    handler = lambda ctx, argv: None
    reg.register("foo", handler, help_text="does foo")
    assert reg.unregister("foo") is handler
    assert reg.lookup("foo") is None
    assert reg.help_text("foo") == ""  # help text is cleaned up too


def test_registry_unregister_unknown_returns_none():
    reg = Registry()
    assert reg.unregister("missing") is None


def test_registry_unregister_none_name_returns_none():
    reg = Registry()
    assert reg.unregister(None) is None


# --- Kernel ---

def test_kernel_execute_unknown_command_writes_error():
    ctx, buffer = make_context()
    kernel = Kernel(registry=Registry(), bus=EventBus())
    kernel.execute("doesnotexist", ctx)
    assert "not found" in full_text(buffer)


def test_kernel_execute_blank_line_is_a_no_op():
    ctx, buffer = make_context()
    kernel = Kernel(registry=Registry(), bus=EventBus())
    kernel.execute("   ", ctx)
    assert row_text(buffer, 0).strip() == ""


def test_kernel_execute_shlex_parse_error_writes_message():
    ctx, buffer = make_context()
    kernel = Kernel(registry=Registry(), bus=EventBus())
    kernel.execute('echo "unterminated', ctx)
    assert "Parse error" in row_text(buffer, 0)


def test_kernel_execute_dispatches_to_registered_handler():
    ctx, buffer = make_context()
    reg = Registry()
    calls = []
    reg.register("greet", lambda c, argv: calls.append(argv))
    kernel = Kernel(registry=reg, bus=EventBus())
    kernel.execute("greet a b", ctx)
    assert calls == [["a", "b"]]


def test_kernel_execute_publishes_event_on_success():
    ctx, buffer = make_context()
    reg = Registry()
    reg.register("noop", lambda c, argv: None)
    bus = EventBus()
    received = []
    bus.subscribe(CommandExecutedEvent, received.append)
    kernel = Kernel(registry=reg, bus=bus)
    kernel.execute("noop x", ctx)
    assert len(received) == 1
    assert received[0].command == "noop"
    assert received[0].args == ["x"]


def test_kernel_execute_handler_exception_is_caught():
    ctx, buffer = make_context()
    reg = Registry()
    def broken(c, argv):
        raise ValueError("boom")
    reg.register("broken", broken)
    bus = EventBus()
    received = []
    bus.subscribe(CommandExecutedEvent, received.append)
    kernel = Kernel(registry=reg, bus=bus)
    kernel.execute("broken", ctx)  # should not raise
    assert "internal error" in full_text(buffer)
    assert received == []  # no event published on failure


# --- echo command ---

def test_echo_writes_joined_arguments():
    ctx, buffer = make_context()
    echo(ctx, ["hello", "world"])
    assert row_text(buffer, 0).startswith("hello world")


def test_echo_with_no_arguments_writes_blank_line():
    ctx, buffer = make_context()
    echo(ctx, [])
    assert row_text(buffer, 0).strip() == ""


def test_echo_help_flag_reports_parse_error_without_raising():
    ctx, buffer = make_context()
    echo(ctx, ["--help"])  # should not raise, writes usage/help instead
    assert row_text(buffer, 0).strip() != ""


# --- color command ---

def test_color_sets_default_fg():
    ctx, buffer = make_context()
    color(ctx, ["--fg", "cyan"])
    assert buffer.default_fg == NAMED_COLORS["cyan"]


def test_color_unknown_fg_writes_error():
    ctx, buffer = make_context()
    color(ctx, ["--fg", "not-a-color"])
    assert "unknown color" in row_text(buffer, 0)


def test_color_unknown_bg_writes_error():
    ctx, buffer = make_context()
    color(ctx, ["--bg", "not-a-color"])
    assert "unknown color" in row_text(buffer, 0)


def test_color_without_omnia_does_not_recolor_existing_cells():
    ctx, buffer = make_context()
    buffer.write_string(0, 0, "hi", fg=NAMED_COLORS["green"])
    color(ctx, ["--fg", "cyan"])
    assert buffer.get_cell(0, 0).fg_color == NAMED_COLORS["green"]


def test_color_with_omnia_recolors_existing_cells_including_scrollback():
    ctx, buffer = make_context(rows=3)
    buffer.write_string(0, 0, "hi", fg=NAMED_COLORS["green"])
    buffer.scroll("u", 2)  # push the written row into scrollback
    color(ctx, ["--fg", "cyan", "--omnia"])
    assert buffer._scrollback[0][0].fg_color == NAMED_COLORS["cyan"]


def test_color_with_no_arguments_is_a_no_op():
    ctx, buffer = make_context()
    original_fg = buffer.default_fg
    color(ctx, [])
    assert buffer.default_fg == original_fg
