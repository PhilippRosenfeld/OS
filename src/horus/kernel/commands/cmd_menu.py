import pyglet

from horus.kernel.registry import command
from horus.ui.menu_screen import MenuScreen, MenuOption


@command("horus", help_text="Open the menu")
def horus_menu(ctx, argv: list[str]) -> None:
    def back_to_shell() -> None:
        ctx.screens.pop()

    def settings() -> None:
        pass #TODO:implement

    def boot_menu() -> None:
        pass #TODO:implement

    def save() -> None:
        pass #TODO:implement

    def quit_game() -> None:
        pyglet.app.exit()

    options = [
        MenuOption("Back to Shell", back_to_shell),
        MenuOption("Settings", settings),
        MenuOption("Save", save),
        MenuOption("To Boot Menu", boot_menu), #Start menu
        MenuOption("Shutdown", quit_game),
    ]
    menu = MenuScreen(ctx.screen, "Menu", options, ctx.screens)
    ctx.screens.push(menu)
