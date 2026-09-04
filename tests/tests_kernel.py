from unittest.mock import patch

import pyglet
import pytest

from horus.display.colors import NAMED_COLORS
from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.events.types import CommandExecutedEvent, ProcessKilledEvent, ProcessStartedEvent
from horus.filesystem.backend.memory import InMemoryVFS
from horus.kernel.commands.cmd_fs import cat, chattr, decrypt, encrypt, ls
from horus.kernel.commands.cmd_menu import horus_menu, open_settings_menu
from horus.kernel.commands.cmd_misc import color, su
from horus.kernel.commands.cmd_proc import kill, top
from horus.kernel.commands.cmd_text import echo
from horus.kernel.kernel import Kernel
from horus.kernel.registry import Registry
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable
from horus.processes.system_reactions import register_system_reactions
from horus.session.context import Context
from horus.session.history import CommandHistory
from horus.session.seed import seed_users
from horus.session.user import UserRegistry
from horus.shell.input_handler import InputHandler
from horus.ui.crash_screen import CrashScreen
from horus.ui.menu_screen import MenuScreen
from horus.ui.screen_manager import ScreenManager
from horus.ui.settings_screen import SettingScreen
from horus.ui.top_screen import TopScreen


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
    def handler(ctx, argv): pass
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
    def handler(ctx, argv): pass
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


# --- su command ---

def make_user_context(cols=60, rows=10):
    buffer = ScreenBuffer(cols, rows)
    history = CommandHistory()
    input_handler = InputHandler(buffer, history)
    users = UserRegistry()
    seed_users(users)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, users=users, input_handler=input_handler)
    return ctx, buffer, input_handler


def test_su_to_unknown_user_writes_error():
    ctx, buffer, _ = make_user_context()
    su(ctx, ["nobody"])
    assert "does not exist" in row_text(buffer, 0)
    assert ctx.effective_user == "root"


def test_su_default_argument_is_root():
    ctx, buffer, _ = make_user_context()
    ctx.user = ctx.effective_user = "user1"
    su(ctx, [])  # no username given -> defaults to "root", and user1 has no rights over root...
    # ...but seed's root has no password, so switching *to* root never asks for one
    assert ctx.effective_user == "root"


def test_root_can_switch_to_anyone_without_a_password():
    ctx, buffer, input_handler = make_user_context()
    su(ctx, ["user1"])  # user1 has a password, but root never needs one
    assert ctx.user == "user1"
    assert ctx.effective_user == "user1"
    assert "switched to user 'user1'" in row_text(buffer, 0)
    assert input_handler._pending_submit is None  # no password prompt happened


def test_switching_to_a_passwordless_user_needs_no_password():
    ctx, buffer, input_handler = make_user_context()
    ctx.user = ctx.effective_user = "user1"  # not root
    su(ctx, ["user2"])  # user2 has no password set
    assert ctx.effective_user == "user2"
    assert input_handler._pending_submit is None


def test_switching_to_a_password_protected_user_prompts_for_one():
    ctx, buffer, input_handler = make_user_context()
    ctx.user = ctx.effective_user = "user2"  # not root, target has a password
    su(ctx, ["user1"])
    assert "Password:" in row_text(buffer, 0)
    assert input_handler._pending_submit is not None
    assert input_handler.masked is True
    assert ctx.effective_user == "user2"  # not switched yet -- still waiting on the password


def test_correct_password_completes_the_switch():
    ctx, buffer, input_handler = make_user_context()
    ctx.user = ctx.effective_user = "user2"
    su(ctx, ["user1"])
    input_handler._pending_submit("password")  # user1's seeded password
    assert ctx.effective_user == "user1"
    assert "switched to user 'user1'" in full_text(buffer)


def test_wrong_password_does_not_switch():
    ctx, buffer, input_handler = make_user_context()
    ctx.user = ctx.effective_user = "user2"
    su(ctx, ["user1"])
    input_handler._pending_submit("wrong-password")
    assert ctx.effective_user == "user2"
    assert "authentication failure" in full_text(buffer)


def test_su_help_flag_reports_parse_error_without_raising():
    ctx, buffer, _ = make_user_context()
    su(ctx, ["--help"])  # argparse's --help exits via CommandParseError; must not propagate
    assert ctx.effective_user == "root"  # no user switch happened


# --- horus / settings menu commands ---

class FakeMenuWindow:
    """Duck-typed stand-in for DisplayWindow, covering exactly what
    open_settings_menu needs, without a real pyglet window/GL context."""

    def __init__(self, width=1920, height=1080, char_width=8, font_path="Px437_IBM_VGA_8x16.ttf"):
        self._window_size = (width, height)
        self.char_width = char_width
        self.font_path = font_path
        self.calls: list[tuple] = []

    @property
    def window_size(self):
        return self._window_size

    def set_window_size(self, w, h):
        self._window_size = (w, h)
        self.calls.append(("set_window_size", w, h))

    def set_char_size(self, w, h):
        self.char_width = w
        self.calls.append(("set_char_size", w, h))

    def set_font(self, path):
        self.font_path = path
        self.calls.append(("set_font", path))


def make_menu_context(cols=80, rows=24):
    buffer = ScreenBuffer(cols, rows)
    screens = ScreenManager()
    window = FakeMenuWindow()
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, screens=screens, window=window)
    return ctx, buffer, screens, window


def test_horus_menu_pushes_a_menu_with_the_expected_options():
    ctx, buffer, screens, window = make_menu_context()
    horus_menu(ctx, [])
    assert isinstance(screens.active, MenuScreen)
    assert [o.label for o in screens.active._options] == [
        "Back to Shell", "Settings", "Save", "To Boot Menu", "Shutdown"]


def test_horus_menu_back_to_shell_pops():
    ctx, buffer, screens, window = make_menu_context()
    screens.push(MenuScreen(buffer, "Shell", [], screens))  # something underneath to reveal
    horus_menu(ctx, [])
    screens.active.handle_enter()  # "Back to Shell" is selected by default
    assert screens.active._title == "Shell"


def test_horus_menu_settings_opens_settings_screen():
    ctx, buffer, screens, window = make_menu_context()
    horus_menu(ctx, [])
    screens.active.handle_motion(pyglet.window.key.MOTION_DOWN)  # select "Settings"
    screens.active.handle_enter()
    assert isinstance(screens.active, SettingScreen)


def test_horus_menu_shutdown_exits_the_app():
    from unittest.mock import patch
    ctx, buffer, screens, window = make_menu_context()
    horus_menu(ctx, [])
    menu = screens.active
    with patch("pyglet.app.exit") as mock_exit:
        for _ in range(4):  # move selection down to "Shutdown" (last option)
            menu.handle_motion(pyglet.window.key.MOTION_DOWN)
        menu.handle_enter()
    mock_exit.assert_called_once()


def test_horus_menu_to_boot_menu_replaces_with_main_menu():
    ctx, buffer, screens, window = make_menu_context()
    sentinel = MenuScreen(buffer, "Main Menu", [], screens)
    ctx.main_menu = sentinel
    horus_menu(ctx, [])
    menu = screens.active
    for _ in range(3):  # move selection to "To Boot Menu"
        menu.handle_motion(pyglet.window.key.MOTION_DOWN)
    menu.handle_enter()
    assert screens.active is sentinel


def test_open_settings_menu_shows_current_window_state():
    ctx, buffer, screens, window = make_menu_context()
    window.char_width = 16  # -> font size "2"
    open_settings_menu(ctx)
    labels = [screens.active._label_for(o) for o in screens.active._options]
    assert "Window Size: < 1920x1080 >" in labels
    assert "Font Size: < 2 >" in labels
    assert "Font: < VGA 8x16 >" in labels


def test_open_settings_menu_right_cycles_window_size():
    import pyglet
    ctx, buffer, screens, window = make_menu_context()
    open_settings_menu(ctx)
    screens.active.handle_motion(pyglet.window.key.MOTION_RIGHT)  # "Window Size" selected by default
    assert window.calls[0][0] == "set_window_size"
    assert window.calls[0][1:] != (1920, 1080)  # moved to a different preset


def test_open_settings_menu_font_size_calls_set_char_size():
    import pyglet
    ctx, buffer, screens, window = make_menu_context()
    open_settings_menu(ctx)
    screens.active.handle_motion(pyglet.window.key.MOTION_DOWN)  # select "Font Size"
    screens.active.handle_motion(pyglet.window.key.MOTION_RIGHT)
    assert window.calls[0][0] == "set_char_size"


def test_open_settings_menu_font_calls_set_font():
    import pyglet
    ctx, buffer, screens, window = make_menu_context()
    open_settings_menu(ctx)
    screens.active.handle_motion(pyglet.window.key.MOTION_DOWN)
    screens.active.handle_motion(pyglet.window.key.MOTION_DOWN)  # select "Font"
    screens.active.handle_motion(pyglet.window.key.MOTION_RIGHT)
    assert window.calls[0] == ("set_font", "Terminus (TTF) 500.ttf")


def test_open_settings_menu_return_pops():
    import pyglet
    ctx, buffer, screens, window = make_menu_context()
    screens.push(MenuScreen(buffer, "Menu", [], screens))
    open_settings_menu(ctx)
    for _ in range(3):  # move selection to "Return"
        screens.active.handle_motion(pyglet.window.key.MOTION_DOWN)
    screens.active.handle_enter()
    assert isinstance(screens.active, MenuScreen)


# --- ls command ---

def test_ls_with_meta_shows_timestamps_without_fractional_seconds():
    buffer = ScreenBuffer(80, 10)
    fs = InMemoryVFS()
    fs.mkdir("/home", user="root")
    fs.write_file("/home/notes", "hi", user="root")  # no '.' in the name, so any '.' in the output can only be a timestamp
    assert fs.get_meta("/home/notes").created_at.microsecond != 0  # backend still stores full precision
    ctx = Context(session_id="s", user="root", cwd="/home", fs=fs, screen=buffer)

    ls(ctx, ["-m"])

    assert "." not in full_text(buffer)  # no fractional-second remainder anywhere in the output


# --- chattr command ---

def test_chattr_with_no_arguments_shows_help():
    """Regression test: this used to raise NameError (_CHATTR_HELP was
    referenced but never defined) instead of showing usage."""
    ctx, buffer = make_context(cols=60, rows=15)  # tall enough that the multi-line help doesn't scroll row 0 out of view
    ctx.fs = InMemoryVFS()
    chattr(ctx, [])  # should not raise
    assert "usage: chattr" in full_text(buffer)


def test_chattr_help_flag_shows_help():
    ctx, buffer = make_context(cols=60, rows=15)
    ctx.fs = InMemoryVFS()
    chattr(ctx, ["--help"])  # should not raise
    assert "usage: chattr" in full_text(buffer)


def test_chattr_sets_a_flag():
    ctx, buffer = make_context(cols=60, rows=10)
    ctx.fs = InMemoryVFS()
    ctx.fs.mkdir("/home", user="root")
    ctx.fs.write_file("/home/secret.txt", "hi", user="root")
    ctx.cwd = "/home"
    chattr(ctx, ["+p", "secret.txt"])
    assert ctx.fs.get_meta("/home/secret.txt").protected is True


def test_chattr_wrong_argument_count_shows_usage():
    ctx, buffer = make_context(cols=60, rows=10)
    ctx.fs = InMemoryVFS()
    chattr(ctx, ["+p"])  # missing path
    assert "usage: chattr <flags> <path>" in full_text(buffer)


# --- cat command ---

def test_cat_prints_file_contents():
    ctx, buffer = make_context()
    ctx.fs = InMemoryVFS()
    ctx.fs.mkdir("/home", user="root")
    ctx.fs.write_file("/home/notes.txt", "hello there\n", user="root")
    ctx.cwd = "/home"

    cat(ctx, ["notes.txt"])

    assert "hello there" in full_text(buffer)


def test_cat_missing_file_writes_error():
    ctx, buffer = make_context(cols=60)
    ctx.fs = InMemoryVFS()

    cat(ctx, ["nope.txt"])

    assert "No such file or directory" in row_text(buffer, 0)


def test_cat_on_a_directory_writes_error():
    """cat checks get_file_type() before reading -- a directory's type is
    '.dir', which isn't in cat's supported list, so it's rejected as 'not a
    text file' rather than reaching the read step at all."""
    ctx, buffer = make_context(cols=60)
    ctx.fs = InMemoryVFS()
    ctx.fs.mkdir("/home", user="root")
    ctx.cwd = "/"

    cat(ctx, ["home"])

    assert "Not a text file" in row_text(buffer, 0)


def test_cat_help_flag_reports_parse_error_without_raising():
    ctx, buffer = make_context()
    ctx.fs = InMemoryVFS()

    cat(ctx, ["--help"])  # should not raise, writes usage/help instead

    assert row_text(buffer, 0).strip() != ""


def test_cat_without_read_permission_writes_error():
    ctx, buffer = make_context(cols=60)
    ctx.fs = InMemoryVFS()
    ctx.fs.mkdir("/home", user="root")
    ctx.fs.write_file("/home/secret.txt", "eyes only", user="root")
    ctx.fs.chmod("/home/secret.txt", mode="700", user="root")
    ctx.cwd = "/home"
    ctx.user = "user1"
    ctx.effective_user = "user1"

    cat(ctx, ["secret.txt"])

    assert "Permission denied" in row_text(buffer, 0)


# --- encrypt / decrypt commands ---

class FakePlayer:
    def __init__(self) -> None:
        self.playing = True

    def pause(self) -> None:
        self.playing = False


class FakeSoundManager:
    """Records play_looped() calls instead of touching pyglet's audio
    backend, and returns a fake Player so tests can check it was paused
    (stopped) once the progress bar completes."""

    def __init__(self) -> None:
        self.looped: list[str] = []
        self.players: list[FakePlayer] = []

    def play_looped(self, name: str) -> FakePlayer:
        self.looped.append(name)
        player = FakePlayer()
        self.players.append(player)
        return player


def make_fs_context(cols=80, rows=10):
    ctx, buffer = make_context(cols=cols, rows=rows)
    ctx.fs = InMemoryVFS()
    ctx.fs.mkdir("/home", user="root")
    ctx.fs.write_file("/home/secret.txt", "top secret", user="root")
    ctx.cwd = "/home"
    ctx.sounds = FakeSoundManager()
    return ctx, buffer


def _run_immediately(fn, *args):
    """encrypt/decrypt show a progress bar via pyglet.clock.schedule_interval
    (see _run_with_progress_bar in cmd_fs.py) that ticks forward by a random
    amount -- occasionally not at all, a stutter -- until it reaches 100%.
    Tests don't want that randomness or a real event loop, so this forces
    the very first tick to jump straight to completion (no stall, full
    100-point step) and fires it immediately."""
    with patch("pyglet.clock.schedule_interval") as mock_schedule, \
         patch("random.random", return_value=1.0), \
         patch("random.uniform", return_value=100.0):
        fn(*args)
        assert mock_schedule.call_count == 1
        callback, interval = mock_schedule.call_args[0]
        callback(0.0)


def test_encrypt_writes_an_immediate_processing_message_and_bar_and_loops_a_sound():
    ctx, buffer = make_fs_context()
    with patch("pyglet.clock.schedule_interval"):  # don't fire it -- check the *immediate* state
        encrypt(ctx, ["secret.txt", "-k", "mykey"])
    assert "Encrypting secret.txt..." in full_text(buffer)
    assert "[" in full_text(buffer) and "0%" in full_text(buffer)  # bar drawn at 0%
    # the actual encryption already happened (checked up front, before any
    # loading UI) -- only *revealing* the "Encrypted:" result is deferred
    assert ctx.fs.exists("/home/secret.txt.crypt") is True
    assert "Encrypted:" not in full_text(buffer)
    assert ctx.sounds.looped == ["crypt"]
    assert ctx.sounds.players[-1].playing is True  # still looping while the bar runs


def test_encrypt_stops_the_looped_sound_once_the_bar_completes():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    assert ctx.sounds.players[-1].playing is False


def test_decrypt_writes_an_immediate_processing_message_and_loops_a_sound():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    with patch("pyglet.clock.schedule_interval"):
        decrypt(ctx, ["secret.txt.crypt", "-k", "mykey"])
    assert "Decrypting secret.txt.crypt..." in full_text(buffer)
    # already restored -- only revealing the "Decrypted:" result is deferred
    assert ctx.fs.exists("/home/secret.txt") is True
    assert "Decrypted:" not in full_text(buffer)
    assert ctx.sounds.looped == ["crypt", "crypt"]


def test_progress_bar_stalls_delay_revealing_the_result():
    ctx, buffer = make_fs_context()
    with patch("pyglet.clock.schedule_interval") as mock_schedule, \
         patch("random.random", return_value=0.0), \
         patch("random.uniform", return_value=50.0):  # 0.0 < stall chance -> always stalls
        encrypt(ctx, ["secret.txt", "-k", "mykey"])
        callback, _ = mock_schedule.call_args[0]
        callback(0.0)
        callback(0.0)
    assert "0%" in full_text(buffer)  # never advanced past the initial render
    assert "Encrypted:" not in full_text(buffer)  # result still not revealed


def test_progress_bar_reveals_the_result_only_after_completion():
    ctx, buffer = make_fs_context()
    with patch("pyglet.clock.schedule_interval") as mock_schedule, \
         patch("random.random", return_value=1.0), \
         patch("random.uniform", return_value=30.0):  # never stalls, +30% per tick
        encrypt(ctx, ["secret.txt", "-k", "mykey"])
        callback, _ = mock_schedule.call_args[0]
        callback(0.0)  # 30%
        callback(0.0)  # 60%
        assert "Encrypted:" not in full_text(buffer)
        callback(0.0)  # 90%
        assert "Encrypted:" not in full_text(buffer)
        callback(0.0)  # 120% -> clamped, done
    assert "Encrypted:" in full_text(buffer)


def test_encrypt_checks_before_showing_any_loading_ui():
    """The encryption is attempted up front -- a failure must be reported
    immediately, without ever printing 'Encrypting...' or scheduling a bar."""
    ctx, buffer = make_fs_context()
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        encrypt(ctx, ["nope.txt", "-k", "mykey"])
    mock_schedule.assert_not_called()
    assert "No such file or directory" in full_text(buffer)
    assert "Encrypting" not in full_text(buffer)


def test_decrypt_checks_before_showing_any_loading_ui():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        decrypt(ctx, ["secret.txt.crypt", "-k", "wrongkey"])
    mock_schedule.assert_not_called()
    assert "wrong key" in full_text(buffer)
    assert "Decrypting" not in full_text(buffer)


# --- encrypt/decrypt key logging ---

def test_encrypt_with_explicit_key_logs_it(caplog):
    ctx, buffer = make_fs_context()
    with caplog.at_level("INFO"):
        encrypt(ctx, ["secret.txt", "-k", "mykey"])
    assert "key='mykey'" in caplog.text


def test_encrypt_with_generated_key_logs_the_generated_one(caplog):
    ctx, buffer = make_fs_context()
    with caplog.at_level("INFO"), patch("pyglet.clock.schedule_interval") as mock_schedule:
        encrypt(ctx, ["secret.txt"])
        callback, _ = mock_schedule.call_args[0]
        with patch("random.random", return_value=1.0), patch("random.uniform", return_value=100.0):
            callback(0.0)  # let the bar finish so "Generated key:" is revealed
    generated_key = full_text(buffer).split("Generated key: ")[1].split(" ")[0]
    assert f"key='{generated_key}'" in caplog.text


def test_encrypt_failure_does_not_log_a_key(caplog):
    ctx, buffer = make_fs_context()
    with caplog.at_level("INFO"):
        encrypt(ctx, ["nope.txt", "-k", "mykey"])
    assert "key=" not in caplog.text


def test_decrypt_with_correct_key_logs_it(caplog):
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    caplog.clear()
    with caplog.at_level("INFO"):
        decrypt(ctx, ["secret.txt.crypt", "-k", "mykey"])
    assert "key='mykey'" in caplog.text


def test_decrypt_with_wrong_key_does_not_log_it(caplog):
    """A failed attempt never actually decrypts anything -- logging the
    guessed key here would just be noise, not a record of what was used."""
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    caplog.clear()
    with caplog.at_level("INFO"):
        decrypt(ctx, ["secret.txt.crypt", "-k", "wrongkey"])
    assert "key=" not in caplog.text
    ctx, buffer = make_fs_context()
    ctx.sounds = None
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    assert ctx.fs.exists("/home/secret.txt.crypt") is True


def test_encrypt_renames_the_file_with_a_crypt_extension():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    assert ctx.fs.exists("/home/secret.txt.crypt") is True
    assert ctx.fs.exists("/home/secret.txt") is False
    assert "Encrypted:" in full_text(buffer)


def test_encrypt_without_a_key_generates_one_and_reports_it():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt"])
    assert "Generated key:" in full_text(buffer)


def test_encrypt_with_a_key_does_not_report_a_generated_key():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    assert "Generated key:" not in full_text(buffer)


def test_encrypted_file_can_no_longer_be_catted():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    cat(ctx, ["secret.txt.crypt"])
    assert "File is encrypted, decrypt it first" in full_text(buffer)


def test_encrypt_missing_file_writes_error():
    ctx, buffer = make_fs_context()
    encrypt(ctx, ["nope.txt", "-k", "mykey"])  # fails the up-front check -- no bar involved
    assert "No such file or directory" in full_text(buffer)


def test_encrypt_a_directory_writes_error():
    ctx, buffer = make_fs_context()
    encrypt(ctx, ["/home", "-k", "mykey"])
    assert "Is a directory" in full_text(buffer)


def test_encrypt_already_encrypted_file_writes_error():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    encrypt(ctx, ["secret.txt.crypt", "-k", "mykey"])
    assert "already encrypted" in full_text(buffer)


def test_decrypt_restores_the_original_file_and_content():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    _run_immediately(decrypt, ctx, ["secret.txt.crypt", "-k", "mykey"])
    assert ctx.fs.exists("/home/secret.txt") is True
    assert ctx.fs.read_file("/home/secret.txt", user="root") == "top secret"


def test_decrypt_with_wrong_key_writes_error_and_keeps_file_encrypted():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    decrypt(ctx, ["secret.txt.crypt", "-k", "wrongkey"])
    assert "wrong key" in full_text(buffer)
    assert ctx.fs.exists("/home/secret.txt.crypt") is True


def test_decrypt_without_key_argument_reports_parse_error():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    decrypt(ctx, ["secret.txt.crypt"])  # -k is required by argparse -- fails before any scheduling happens
    assert ctx.fs.exists("/home/secret.txt.crypt") is True


def test_decrypt_a_non_encrypted_file_writes_error():
    ctx, buffer = make_fs_context()
    decrypt(ctx, ["secret.txt", "-k", "mykey"])
    assert "not encrypted" in full_text(buffer)


def test_decrypt_with_wrong_method_writes_error_even_with_the_right_key():
    """The method must match exactly like the key -- it's not auto-detected
    or hinted at, so guessing it wrong fails the same way a wrong key does."""
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey", "-m", "xor"])
    decrypt(ctx, ["secret.txt.crypt", "-k", "mykey", "-m", "aes"])
    assert "wrong key or method" in full_text(buffer)
    assert ctx.fs.exists("/home/secret.txt.crypt") is True


def test_decrypt_default_method_is_xor_matching_encrypts_default():
    ctx, buffer = make_fs_context()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])  # default method: xor
    _run_immediately(decrypt, ctx, ["secret.txt.crypt", "-k", "mykey"])  # default method: xor
    assert ctx.fs.exists("/home/secret.txt") is True


def test_encrypt_help_flag_reports_parse_error_without_raising():
    ctx, buffer = make_fs_context()
    encrypt(ctx, ["--help"])  # fails during parsing, before any scheduling happens
    assert ctx.fs.exists("/home/secret.txt") is True  # untouched


# --- encrypt/decrypt permission checks (protected -> ADMIN+, immutable -> ROOT) ---

def make_fs_context_with_users(cols=80, rows=10):
    ctx, buffer = make_fs_context(cols=cols, rows=rows)
    ctx.users = UserRegistry()
    seed_users(ctx.users)
    return ctx, buffer


def test_encrypt_protected_file_denies_a_plain_user():
    ctx, buffer = make_fs_context_with_users()
    ctx.fs.set_attributes("/home/secret.txt", user="root", protected=True)
    ctx.user = ctx.effective_user = "user1"
    encrypt(ctx, ["secret.txt", "-k", "mykey"])
    assert "Permission denied" in full_text(buffer)
    assert ctx.fs.exists("/home/secret.txt.crypt") is False


def test_encrypt_protected_file_allows_admin():
    ctx, buffer = make_fs_context_with_users()
    ctx.fs.set_attributes("/home/secret.txt", user="root", protected=True)
    ctx.user = ctx.effective_user = "admin"
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    assert ctx.fs.exists("/home/secret.txt.crypt") is True


def test_encrypt_immutable_file_denies_admin():
    """Immutable is a stricter tier than protected -- ADMIN is enough for a
    protected file, but not for an immutable one."""
    ctx, buffer = make_fs_context_with_users()
    ctx.fs.set_attributes("/home/secret.txt", user="root", immutable=True)
    ctx.user = ctx.effective_user = "admin"
    encrypt(ctx, ["secret.txt", "-k", "mykey"])
    assert "Permission denied" in full_text(buffer)
    assert ctx.fs.exists("/home/secret.txt.crypt") is False


def test_encrypt_immutable_file_allows_root_directly():
    ctx, buffer = make_fs_context_with_users()
    ctx.fs.set_attributes("/home/secret.txt", user="root", immutable=True)
    ctx.user = ctx.effective_user = "root"
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    assert ctx.fs.exists("/home/secret.txt.crypt") is True


def test_encrypt_without_a_user_registry_falls_back_to_least_privilege():
    """No ctx.users at all (e.g. a minimal test context) must fail closed --
    a protected file stays out of reach rather than silently allowing it."""
    ctx, buffer = make_fs_context()  # no .users set
    ctx.fs.set_attributes("/home/secret.txt", user="root", protected=True)
    ctx.user = ctx.effective_user = "someone"
    encrypt(ctx, ["secret.txt", "-k", "mykey"])
    assert "Permission denied" in full_text(buffer)


# --- encrypt/decrypt spawn a visible process for the duration of the operation ---

def make_fs_context_with_process_table():
    ctx, buffer = make_fs_context()
    ctx.events = EventBus()
    ctx.process_table = ProcessTable(events=ctx.events)
    return ctx, buffer


def test_encrypt_spawns_a_process_while_the_bar_runs():
    ctx, buffer = make_fs_context_with_process_table()
    with patch("pyglet.clock.schedule_interval"):  # don't fire it -- check the *immediate* state
        encrypt(ctx, ["secret.txt", "-k", "mykey"])
    procs = ctx.process_table.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "encrypt"
    assert procs[0].owner == "root"


def test_encrypt_removes_the_process_once_the_bar_completes():
    ctx, buffer = make_fs_context_with_process_table()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    assert ctx.process_table.list_processes() == []


def test_decrypt_spawns_and_removes_its_own_process():
    ctx, buffer = make_fs_context_with_process_table()
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])
    with patch("pyglet.clock.schedule_interval"):
        decrypt(ctx, ["secret.txt.crypt", "-k", "mykey"])
    procs = ctx.process_table.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "decrypt"


def test_encrypt_publishes_process_started_and_killed_events():
    ctx, buffer = make_fs_context_with_process_table()
    received = []
    ctx.events.subscribe(ProcessStartedEvent, received.append)
    ctx.events.subscribe(ProcessKilledEvent, received.append)

    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])

    assert len(received) == 2
    assert isinstance(received[0], ProcessStartedEvent)
    assert received[0].name == "encrypt"
    assert received[0].owner == "root"
    assert isinstance(received[1], ProcessKilledEvent)
    assert received[1].name == "encrypt"
    assert received[1].pid == received[0].pid


def test_encrypt_failure_never_spawns_a_process():
    """The up-front check happens before any process/bar exists -- a failure
    must not leave a phantom process behind."""
    ctx, buffer = make_fs_context_with_process_table()
    encrypt(ctx, ["nope.txt", "-k", "mykey"])
    assert ctx.process_table.list_processes() == []


def test_encrypt_without_a_process_table_does_not_raise():
    ctx, buffer = make_fs_context()  # ctx.process_table stays None
    _run_immediately(encrypt, ctx, ["secret.txt", "-k", "mykey"])  # should not raise
    assert ctx.fs.exists("/home/secret.txt.crypt") is True


# --- top command ---

def make_proc_context(cols=60, rows=10):
    buffer = ScreenBuffer(cols, rows)
    screens = ScreenManager()
    table = ProcessTable()
    table.add_process(Process(name="init", pid=0, owner="root", cpu_percent=0.1, mem_kb=1024))
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, screens=screens, process_table=table)
    return ctx, buffer, screens, table


def test_top_pushes_a_live_top_screen():
    ctx, buffer, screens, table = make_proc_context()
    top(ctx, [])
    assert isinstance(screens.active, TopScreen)


def test_top_without_a_screen_stack_falls_back_to_a_one_shot_snapshot():
    ctx, buffer = make_context()
    ctx.process_table = ProcessTable()
    ctx.process_table.add_process(Process(name="init", pid=0, owner="root", cpu_percent=0.1, mem_kb=1024))
    top(ctx, [])
    assert "init" in full_text(buffer)
    assert ctx.screens is None  # nothing to push onto -- confirms the fallback path ran


def test_top_help_flag_reports_parse_error_without_pushing_a_screen():
    ctx, buffer, screens, table = make_proc_context()
    top(ctx, ["--help"])
    assert screens.active is None


# --- kill command ---

def make_kill_context(cols=60, rows=10):
    """Builds its own EventBus (rather than reusing make_proc_context's
    table) and registers the real system-reaction subscriber on it, so
    killing the critical 'init' process here exercises the same event-driven
    path production code does -- not a direct CrashScreen push from kill()
    itself (see processes.system_reactions)."""
    buffer = ScreenBuffer(cols, rows)
    screens = ScreenManager()
    bus = EventBus()
    table = ProcessTable(events=bus)
    proc = table.add_process(Process(name="init", pid=0, owner="root", cpu_percent=0.1, mem_kb=1024, critical=True))
    other = table.add_process(Process(name="bash", pid=0, owner="user1", cpu_percent=0.5, mem_kb=2048))
    users = UserRegistry()
    seed_users(users)
    input_handler = InputHandler(buffer, CommandHistory())  # kill's confirmation prompt needs this
    register_system_reactions(bus, screens, window=None, sounds=None, buffer=buffer)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, screens=screens, process_table=table,
                  users=users, input_handler=input_handler, events=bus)
    return ctx, buffer, table, proc, other


def test_kill_by_owner_succeeds():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "user1"
    kill(ctx, [str(other.pid)])
    assert table.get_process(other.pid) is None
    assert "Killed process" in full_text(buffer)


def test_kill_someone_elses_process_as_plain_user_is_denied():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "user2"
    kill(ctx, [str(other.pid)])
    assert table.get_process(other.pid) is not None
    assert "Operation not permitted" in full_text(buffer)


def test_kill_someone_elses_process_as_admin_succeeds():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "admin"
    kill(ctx, [str(other.pid)])
    assert table.get_process(other.pid) is None
    assert "Killed process" in full_text(buffer)


def test_kill_someone_elses_process_as_root_succeeds():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "root"
    kill(ctx, [str(other.pid)])
    assert table.get_process(other.pid) is None


def test_kill_unknown_pid_reports_no_such_process():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "root"
    kill(ctx, ["999"])
    assert "No such process" in full_text(buffer)


def test_kill_without_a_user_registry_fails_closed_for_someone_elses_process():
    """No ctx.users at all must resolve to the least-privileged role, not
    silently allow killing someone else's process."""
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.users = None
    ctx.user = ctx.effective_user = "user2"
    kill(ctx, [str(other.pid)])
    assert table.get_process(other.pid) is not None
    assert "Operation not permitted" in full_text(buffer)


def test_kill_help_flag_reports_parse_error_without_raising():
    ctx, buffer, table, proc, other = make_kill_context()
    kill(ctx, ["--help"])  # should not raise
    assert table.get_process(other.pid) is not None  # untouched


# --- kill on a critical process: warning + y/n confirmation, then a crash ---

def test_kill_critical_process_shows_a_warning_and_asks_for_confirmation():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "root"
    kill(ctx, [str(proc.pid)])
    assert "critical system process" in full_text(buffer)
    assert "(y/n)" in full_text(buffer)
    assert ctx.input_handler._pending_submit is not None
    assert table.get_process(proc.pid) is not None  # not killed yet -- still waiting on the answer


def test_kill_critical_process_confirmed_kills_it_and_crashes():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "root"
    kill(ctx, [str(proc.pid)])
    with patch("pyglet.clock.schedule_once"):  # don't actually schedule the real window-close timer
        ctx.input_handler._pending_submit("y")
    assert table.get_process(proc.pid) is None
    assert isinstance(ctx.screens.active, CrashScreen)


def test_kill_critical_process_declined_leaves_it_running():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "root"
    kill(ctx, [str(proc.pid)])
    ctx.input_handler._pending_submit("n")
    assert table.get_process(proc.pid) is not None
    assert "aborted" in full_text(buffer)
    assert not isinstance(ctx.screens.active, CrashScreen)


def test_kill_critical_process_without_permission_never_shows_the_warning():
    """A plain user isn't authorized at all -- they shouldn't even get the
    dramatic warning/confirmation for a process they could never touch."""
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "user2"
    kill(ctx, [str(proc.pid)])
    assert "critical system process" not in full_text(buffer)
    assert "Operation not permitted" in full_text(buffer)
    assert ctx.input_handler._pending_submit is None
    assert table.get_process(proc.pid) is not None


def test_kill_critical_process_confirmed_by_admin_also_crashes():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "admin"
    kill(ctx, [str(proc.pid)])
    with patch("pyglet.clock.schedule_once"):
        ctx.input_handler._pending_submit("yes")
    assert table.get_process(proc.pid) is None
    assert isinstance(ctx.screens.active, CrashScreen)


def test_kill_non_critical_process_never_asks_for_confirmation():
    ctx, buffer, table, proc, other = make_kill_context()
    ctx.user = ctx.effective_user = "user1"
    kill(ctx, [str(other.pid)])  # "bash", not critical
    assert table.get_process(other.pid) is None
    assert ctx.input_handler._pending_submit is None
    assert not isinstance(ctx.screens.active, CrashScreen)
