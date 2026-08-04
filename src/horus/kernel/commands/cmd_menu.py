import pyglet

from horus.kernel.registry import command
from horus.ui.menu_screen import MenuScreen, MenuOption


@command("horus", help_text="Open the menu")
def horus_menu(ctx, argv: list[str]) -> None:
    def back_to_shell() -> None:
        ctx.screens.pop()

    def quit_game() -> None:
        pyglet.app.exit()

    options = [
        MenuOption("Back to Shell", back_to_shell),
        MenuOption("Quit", quit_game),
    ]
    menu = MenuScreen(ctx.screen, "Menu", options, ctx.screens)
    ctx.screens.push(menu)
