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
from horus.ui.boot_screen import BootScreen, BootFrame
from horus.paths import SAVES_DIR, DATA_DIR
from horus.session.user import UserRegistry, User, UserRole
from horus.session.seed import seed_users
from horus.session.auth import hash_password
from horus.__about__ import VERSION
from horus.story.progress import BootProgress
from horus.paths import BOOT_PROGRESS_PATH, BOOT_DIR
from horus.hardware.spec import HardwareSpec
from horus.paths import HARDWARE_SPEC_PATH
from horus.ui.logo_screen import LogoScreen
from pathlib import Path
from horus.ui.main_menu_screen import MainMenuScreen
from horus.ui.settings_screen import SettingScreen, SettingOption
from horus.kernel.commands.cmd_menu import open_settings_menu
from horus.ui.menu_screen import MenuScreen, MenuOption


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

    def _load_boot_frames(path, context: dict[str, str] = None) -> list[BootFrame]:
        """context provides {placeholder} values substituted into each line,
        e.g. {'version': '0.3.0'}."""
        context = context or {}
        frames = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, raw_line in enumerate(f, start=1):
                line = raw_line.rstrip("\n")
                if not line:
                    continue

                delay_str, sep, text = line.partition("|")
                if not sep:
                    text, delay = line, 0.05
                else:
                    try:
                        delay = float(delay_str)
                    except ValueError:
                        logger.warning(f"boot sequence line {line_num} has invalid delay '{delay_str}', using default")
                        delay = 0.05

                try:
                    text = text.format(**context)
                except KeyError as e:
                    logger.warning(f"boot sequence line {line_num} references unknown placeholder {e}")

                frames.append(BootFrame(text=text, delay=delay))

        logger.debug(f"loaded {len(frames)} boot frames from {path}")
        return frames

    def _load_logo_lines(path: Path) -> list[str]:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
            
    history = CommandHistory()
    input_handler = InputHandler(window.buffer, history, on_submit=on_submit, get_prompt=get_prompt)
    context.input_handler = input_handler

    logo_lines = _load_logo_lines(BOOT_DIR / "logo.txt")


    def _start_shell() -> None:
        screens.pop()

    def _open_settings() -> None:
        open_settings_menu(context)

    def _exit_game() -> None:
        window.close() 

    main_menu = MainMenuScreen(
        window.buffer,
        title="H O R U S   S Y S T E M S",
        options=[
            MenuOption("Continue", _start_shell),
            MenuOption("Settings", _open_settings),
            MenuOption("Exit", _exit_game),
        ],
    )

    def _on_boot_complete() -> None:
        screens.pop()
        screens.push(LogoScreen(window.buffer, logo_lines, on_complete=_on_logo_complete))
    
    def _on_logo_complete() -> None:
        screens.pop()
        screens.push(main_menu) 

    window.set_text_handler(
        on_text=screens.handle_text,
        on_motion=screens.handle_motion,
        on_enter=screens.handle_enter,
        on_key=screens.handle_key,
    )

    boot_progress = BootProgress.load(BOOT_PROGRESS_PATH)
    latest_disk = boot_progress.latest_ok_disk()
    boot_disk_name = f"Disk {latest_disk}" if latest_disk is not None else "Disk 0 (recovery mode)"
    disk_context = {
        f"disk{d}_{c}": boot_progress.status(f"disk{d}_{c}")
        for d in (1, 2, 3)
        for c in (1, 2, 3)
    }
    hardware = HardwareSpec.load(HARDWARE_SPEC_PATH)

    frames = _load_boot_frames(DATA_DIR / "boot" / "boot_sequence.txt",
        context={
            "version": VERSION, 
            "memory_size": hardware.memory_kb,
            "memory_count": hardware.memory_count,
            "cpu_cores": hardware.cpu_cores,
            "cpu_name": hardware.cpu_name,
            "cpu_mhz": hardware.cpu_mhz,
            "coolant_type": hardware.coolant_type,
            "coolant_amount": hardware.coolant_amount,
            "boot_disk": boot_disk_name,
            **disk_context})
    
    shell_screen = ShellScreen(input_handler, screens)
    screens.push(shell_screen)
    boot_screen = BootScreen(window.buffer, frames, on_complete=_on_boot_complete)
    screens.push(boot_screen)

    window.run()