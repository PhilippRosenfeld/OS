from horus.display.window import DisplayWindow
from horus.shell.input_handler import InputHandler
from horus.utils.config_manager import load_config
from horus.utils.logging_setup import setup_logging
from horus.kernel.kernel import Kernel
from horus.kernel.registry import registry
from horus.session.context import Context
from horus.events.bus import EventBus
from horus.filesystem.backend.memory import InMemoryVFS
from horus.filesystem.seed import seed_minimal

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
    fs = InMemoryVFS()
    seed_minimal(fs)

    context = Context(
        session_id = "local",
        user="root",
        cwd="/home",
        fs=fs,
        screen=window.buffer,
        events=bus
    )

    def on_submit(line: str) -> None:
        kernel.execute(line, context)


    input_handler = InputHandler(window.buffer, on_submit=on_submit)
    window.set_text_handler(
        on_text=input_handler._handle_text,
        on_motion=input_handler._handle_motion,
        on_enter=input_handler._handle_enter,
        on_key=input_handler._handle_key,
    )
    window.start_cursor_blink()
    window.run()