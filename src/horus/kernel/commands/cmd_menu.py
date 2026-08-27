import pyglet

from horus.kernel.registry import command
from horus.ui.menu_screen import MenuScreen, MenuOption
from horus.ui.settings_screen import SettingOption, SettingScreen

_WINDOW_SIZES = [(1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)]
_CHAR_SIZES = [1, 2, 3, 4, 5, 6]
_FONTS = [
    ("VGA 8x16", "Px437_IBM_VGA_8x16.ttf"),
    ("Terminus", "Terminus (TTF) 500.ttf"),
]


def _closest_index(values: list[int], current: int) -> int:
    """Index of the closest entry to `current` -- used so the settings menu shows
    the actual current value even if it was reached outside the menu (e.g. by
    dragging the window edge instead of cycling 'Window Size')."""
    return min(range(len(values)), key=lambda i: abs(values[i] - current))


@command("horus", help_text="Open the menu")
def horus_menu(ctx, argv: list[str]) -> None:
    """Opens the game menu."""
    
    def back_to_shell() -> None:
        ctx.screens.pop()

    def settings() -> None:
        open_settings_menu(ctx)

    def boot_menu() -> None:
        ctx.screens.pop()  # close this "Menu" screen
        ctx.screens.push(ctx.main_menu)  # back to the title screen; shell stays preserved underneath

    def save() -> None:
        pass #TODO:implement

    def quit_game() -> None:
        pyglet.app.exit()

    options = [
        MenuOption("Back to Shell", back_to_shell),
        MenuOption("Settings", settings),
        MenuOption("Save", save),
        MenuOption("To Boot Menu", boot_menu),
        MenuOption("Shutdown", quit_game),
    ]
    menu = MenuScreen(ctx.screen, "Menu", options, ctx.screens)
    ctx.screens.push(menu)
    

def open_settings_menu(ctx) -> None:
    """Sub-menu for settings: window size, font size, and font, each cycled with
    Left/Right and applied live via ctx.window."""

    window_index = _closest_index([w for w, h in _WINDOW_SIZES], ctx.window.window_size[0])
    char_index = _closest_index(_CHAR_SIZES, ctx.window.char_width // 8)
    font_paths = [path for _, path in _FONTS]
    font_index = font_paths.index(ctx.window.font_path) if ctx.window.font_path in font_paths else 0

    def window_size_value() -> str:
        w, h = _WINDOW_SIZES[window_index]
        return f"{w}x{h}"

    def window_size_step(delta: int) -> None:
        nonlocal window_index
        window_index = (window_index + delta) % len(_WINDOW_SIZES)
        ctx.window.set_window_size(*_WINDOW_SIZES[window_index])

    def font_size_value() -> str:
        return str(_CHAR_SIZES[char_index])

    def font_size_step(delta: int) -> None:
        nonlocal char_index
        char_index = (char_index + delta) % len(_CHAR_SIZES)
        size = _CHAR_SIZES[char_index]
        ctx.window.set_char_size(8 * size, 16 * size)

    def font_value() -> str:
        return _FONTS[font_index][0]

    def font_step(delta: int) -> None:
        nonlocal font_index
        font_index = (font_index + delta) % len(_FONTS)
        ctx.window.set_font(_FONTS[font_index][1])

    def back_to_menu() -> None:
        ctx.screens.pop()

    settingOptions = [
        SettingOption("Window Size", get_value=window_size_value, on_left=lambda: window_size_step(-1), on_right=lambda: window_size_step(1)),
        SettingOption("Font Size", get_value=font_size_value, on_left=lambda: font_size_step(-1), on_right=lambda: font_size_step(1)),
        SettingOption("Font", get_value=font_value, on_left=lambda: font_step(-1), on_right=lambda: font_step(1)),
        SettingOption("Return", on_select=back_to_menu),
    ]
    settingsScreen = SettingScreen(ctx.screen, "Settings", settingOptions, ctx.screens)
    ctx.screens.push(settingsScreen)
