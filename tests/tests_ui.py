import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager
from horus.ui.shell_screen import ShellScreen
from horus.ui.menu_screen import MenuScreen, MenuOption
from horus.ui.settings_screen import SettingScreen, SettingOption
from horus.ui.boot_screen import BootScreen, BootFrame
from horus.ui.logo_screen import LogoScreen
from horus.ui.main_menu_screen import MainMenuScreen, MenuOption as MainMenuOption
from horus.shell.input_handler import InputHandler
from horus.session.history import CommandHistory

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
    assert row_text(buffer, 0) == "Menu"  # not clobbered by the shell's prompt


def test_shell_screen_redraws_prompt_when_menu_above_it_closes():
    buffer = ScreenBuffer(20, 5)
    manager = ScreenManager()
    history = CommandHistory()
    handler = InputHandler(buffer, history, get_prompt=lambda: "> ")
    shell = ShellScreen(handler, manager)
    manager.push(shell)
    menu = MenuScreen(buffer, "Menu", [MenuOption("Back", lambda: manager.pop())], manager)
    manager.push(menu)
    assert row_text(buffer, 0) == "Menu"

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

    assert row_text(buffer, 0) == "Settings"
    assert row_text(buffer, 2) == "> Window Size: <"[:15].rstrip()  # cut off cleanly, not garbled
    for row in range(buffer.rows):
        assert "900" not in row_text(buffer, row)  # no wrapped/stale tail from the wider render


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
        self.sound_volumes: dict[str, float] = {}
        self.fade_ins: list[tuple[str, float, float, bool]] = []
        self.play_players: dict[str, FakePlayer] = {}  # name -> the player returned by play()

    def play(self, name: str) -> FakePlayer:
        self.played.append(name)
        player = FakePlayer(loop=False)
        self.play_players[name] = player
        return player

    def fade_out(self, target_volume: float, duration: float, on_complete=None) -> None:
        self.fades.append((target_volume, duration))
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
