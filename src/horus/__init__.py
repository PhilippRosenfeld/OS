from horus.display.window import DisplayWindow
from horus.shell.input_handler import InputHandler
from horus.utils.config_manager import load_config
from horus.utils.logging_setup import setup_logging
from horus.kernel.kernel import Kernel
from horus.kernel.registry import registry
from horus.session.context import Context
from horus.session.history import CommandHistory
from horus.events.bus import EventBus
from horus.filesystem.backend.sqlite import SQLiteVFS
from horus.filesystem.seed import seed_minimal
from horus.ui.screen_manager import ScreenManager
from horus.ui.shell_screen import ShellScreen
from horus.paths import SAVES_DIR
from horus.session.user import UserRegistry, User, UserRole
from horus.session.seed import seed_users
from horus.session.auth import hash_password

import horus.kernel.commands
import logging


cfg = load_config()
char_size = cfg['display']['char_size']
setup_logging(level=cfg['debug_level'], log_file="horus.log")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("-------------------- Application started --------------------")
    window = DisplayWindow(font_path = "Px437_IBM_VGA_8x16.ttf", height=1080, title="Horus OS", char_width=8*char_size, char_height=16*char_size, margin=8)
    

    bus = EventBus()
    kernel = Kernel(registry=registry, bus=bus)
    fs = SQLiteVFS(SAVES_DIR / "horus.db")
    if fs.is_empty():
        seed_minimal(fs)

    screens = ScreenManager()
    users = UserRegistry()
    seed_users(users)

    context = Context(
        session_id = "local",
        user="root",
        cwd="/home",
        fs=fs,
        screen=window.buffer,
        events=bus,
        screens=screens,
        window=window,
        users=users,
        kernel=kernel,
    )

    def on_submit(line: str) -> None:
        kernel.execute(line, context)

    def get_prompt() -> str:
        return f"{context.user}@{context.cwd} > "

    history = CommandHistory()
    input_handler = InputHandler(window.buffer, history, on_submit=on_submit, get_prompt=get_prompt)
    context.input_handler = input_handler

    screens.push(ShellScreen(input_handler, screens))

    window.set_text_handler(
        on_text=screens.handle_text,
        on_motion=screens.handle_motion,
        on_enter=screens.handle_enter,
        on_key=screens.handle_key,
    )
    window.start_cursor_blink()
    window.run()