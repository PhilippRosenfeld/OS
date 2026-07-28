from horus.display.window import DisplayWindow
from horus.shell.input_handler import InputHandler
from horus.utils.config_manager import load_config
from horus.utils.logging_setup import setup_logging
from horus.kernel.kernel import Kernel
from horus.kernel.registry import Registry
from horus.session.context import Context
from horus.events.bus import EventBus
import logging


setup_logging(level=logging.INFO, log_file="horus.log")

cfg = load_config()
char_size = cfg['display']['char_size']

#Terminus (TTF) 500.ttf       Px437_IBM_VGA_8x16.ttf


def main() -> None:
    window = DisplayWindow(font_path = "Px437_IBM_VGA_8x16.ttf", height=1080, title="Horus OS", char_width=8*char_size, char_height=16*char_size, margin=8)
    
    registry = Registry()
    bus = EventBus()
    kernel = Kernel(registry=registry, bus=bus)

    context = Context(
        session_id = "local",
        user="root",
        cwd="/",
        fs=None,
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