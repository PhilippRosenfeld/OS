import logging
from pathlib import Path

import horus.kernel.commands
from horus.__about__ import VERSION
from horus.audio.sound_manager import SoundManager
from horus.display.window import DisplayWindow
from horus.events.bus import EventBus
from horus.events.system_log import SystemLog
from horus.filesystem.backend.sqlite import SQLiteVFS
from horus.filesystem.disk_usage import ensure_mount_points
from horus.filesystem.seed import seed_minimal
from horus.hardware.spec import HardwareSpec
from horus.kernel.commands.cmd_menu import horus_menu, open_settings_menu
from horus.kernel.kernel import Kernel
from horus.kernel.registry import registry
from horus.paths import BOOT_DIR, BOOT_PROGRESS_PATH, DATA_DIR, HARDWARE_SPEC_PATH, SAVES_DIR, SOUNDS_DIR
from horus.processes.memory import MemoryManager
from horus.processes.processTable import ProcessTable
from horus.processes.scheduler import CpuScheduler
from horus.processes.seed_process import seed_processes
from horus.processes.system_reactions import (
    register_memory_reactions,
    register_power_reactions,
    register_status_bar,
    register_storage_reactions,
    register_system_log,
    register_system_reactions,
    register_temperature_reactions,
)
from horus.session.context import Context
from horus.session.history import CommandHistory
from horus.session.seed import seed_users
from horus.session.user import UserRegistry
from horus.shell.completion import complete_path
from horus.shell.input_handler import InputHandler
from horus.story.progress import BootProgress
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.boot_screen import BootFrame, BootScreen
from horus.ui.screens.cpu_screen import CpuScreen
from horus.ui.screens.crash_screen import CrashScreen
from horus.ui.screens.detail_screen import DetailScreen
from horus.ui.screens.hardware_screen import HardwareScreen
from horus.ui.screens.logo_screen import LogoScreen
from horus.ui.screens.main_menu_screen import MainMenuScreen
from horus.ui.screens.menu_screen import MenuOption, MenuScreen
from horus.ui.screens.ram_screen import RamScreen
from horus.ui.screens.settings_screen import SettingScreen
from horus.ui.screens.shell_screen import ShellScreen
from horus.utils.config_manager import load_config
from horus.utils.logging_setup import setup_logging

cfg = load_config()
char_size = cfg['display']['char_size']
# boot/logo/menus/sys/crash are laid out for one known size and ignore the
# user's font size (see _on_before_screen_activate below)
fixed_char_size = cfg['display'].get('fixed_char_size', char_size)
setup_logging(level=cfg['debug_level'], log_file="horus.log")
logger = logging.getLogger(__name__)

_FIXED_CHAR_SIZE_SCREENS = (
    BootScreen, LogoScreen, MainMenuScreen, MenuScreen, SettingScreen,  # boot, logo, main menu, menus
    HardwareScreen, DetailScreen, CpuScreen, RamScreen,                 # sys (and its detail screens)
    CrashScreen,
)


def main() -> None:
    logger.info("-------------------- Application started --------------------")
    
    # ---- DISPLAY -----
    window = DisplayWindow(font_path = "Px437_IBM_VGA_8x16.ttf",
                           title="Horus OS",
                           char_width=8*char_size,
                           char_height=16*char_size,
                           margin=8,
                           fullscreen=cfg['display']['fullscreen'],
                           width=cfg['display']['width'],
                           height=cfg['display']['height'])
    

    # ----- SOUNDS -----
    sounds = SoundManager()
    sounds.set_volume(cfg['sound']['volume'])
    sounds.load_all_from_directory(SOUNDS_DIR)

    #---- KERNEL -----
    bus = EventBus()
    kernel = Kernel(registry=registry, bus=bus)
    
    #--- FILESYSTEM -----
    fs = SQLiteVFS(SAVES_DIR / "horus.db")
    if fs.is_empty():
        seed_minimal(fs)

    def _on_active_screen_changed(screen) -> None:
        # The status bar (see DisplayWindow.status_bar) is only meaningful
        # while the interactive shell is what's on screen -- boot/menus/
        # settings/etc. all hide it again.
        window.status_bar.set_visible(isinstance(screen, ShellScreen))

    def _on_before_screen_activate(screen) -> None:
        # Screens with a fixed layout always get the configured
        # display.fixed_char_size, never the user's font size -- everything
        # else (shell, top, ...) goes back to the user's own size.
        if isinstance(screen, _FIXED_CHAR_SIZE_SCREENS):
            window.set_fixed_char_size((8 * fixed_char_size, 16 * fixed_char_size))
        else:
            window.set_fixed_char_size(None)

    #---- SCREENS -----
    screens = ScreenManager(on_active_changed=_on_active_screen_changed,
                            on_before_activate=_on_before_screen_activate)
    
    #---- USERS -----
    users = UserRegistry()
    seed_users(users)

    #--- HARDWARE -----
    hardware = HardwareSpec.load(HARDWARE_SPEC_PATH)
    ensure_mount_points(fs, hardware.installed_storage())

    #--- PROCESSES -----
    process_table = ProcessTable(events=bus, total_memory_kb=hardware.total_memory_kb(),
                                  total_cpu_mhz=hardware.total_cpu_mhz())
    seed_processes(process_table)
    process_table.start_fluctuating()
    cpu_scheduler = CpuScheduler(process_table, hardware)  # pins processes to cores, tracks CPU time
    cpu_scheduler.start()
    memory_manager = MemoryManager(process_table, hardware, events=bus, fs=fs)  # RAM pages, swap, OOM, memory errors
    memory_manager.start()
    
    hardware.start_power_monitoring(process_table, bus)
    
    #--- SYSTEM REACTIONS -----
    register_system_reactions(bus, screens, window, sounds, window.buffer)
    register_power_reactions(bus, sounds)
    register_memory_reactions(bus, sounds)
    register_storage_reactions(bus, sounds)
    register_temperature_reactions(bus, screens, window, sounds, window.buffer)
    system_log = SystemLog()
    register_system_log(bus, system_log)
    register_status_bar(bus, window.status_bar)
    window.status_bar.start_blinking()

    # ---- CONTEXT -----
    context = Context(
        session_id = "local",
        user="root",
        cwd="/",
        fs=fs,
        screen=window.buffer,
        events=bus,
        sounds=sounds,
        screens=screens,
        window=window,
        users=users,
        kernel=kernel,
        process_table=process_table,
        hardware=hardware,
        system_log=system_log,
        cpu_scheduler=cpu_scheduler,
        memory_manager=memory_manager,
    )

    def on_submit(line: str) -> None:
        kernel.execute(line, context)

    def get_prompt() -> str:
        return f"{context.user}@{context.cwd} > "

    def complete_file(prefix: str) -> list[str]:
        return complete_path(fs, context.cwd, prefix)

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
    
    # ---- INPUT HANDLER -----
    history = CommandHistory()
    input_handler = InputHandler(window.buffer, history, on_submit=on_submit, get_prompt=get_prompt, complete=complete_file)
    context.input_handler = input_handler

    logo_lines = _load_logo_lines(BOOT_DIR / "logo.txt")


    def _start_shell() -> None:
        screens.pop()
        # BootScreen only fades hard_disk_spinup down to near-silent (not
        # off) at boot _finish(), so it can still be quietly running all the
        # way through Logo and the Main Menu -- actually silence it here
        sounds.fade_out(0.0, duration=2.0, name="hard_disk_spinup")

    def _open_settings() -> None:
        open_settings_menu(context)

    def _open_horus_menu() -> None:
        horus_menu(context, [])

    def _exit_game() -> None:
        window.close() 

    # ---- MAIN MENU -----
    main_menu = MainMenuScreen(
        window.buffer,
        title="H O R U S   S Y S T E M S",
        options=[
            MenuOption("Continue", _start_shell),
            MenuOption("Settings", _open_settings),
            MenuOption("Exit", _exit_game),
        ],
        sounds=sounds,
        song="menu_music",
    )
    context.main_menu = main_menu

    def _on_boot_complete() -> None:
        screens.replace(LogoScreen(window.buffer, logo_lines, on_complete=_on_logo_complete, sounds=sounds))

    def _on_logo_complete() -> None:
        screens.replace(main_menu)
        sounds.fade_in("background", target_volume=0.075, duration=5.0, loop=True)

    window.set_text_handler(
        on_text=screens.handle_text,
        on_motion=screens.handle_motion,
        on_enter=screens.handle_enter,
        on_key=screens.handle_key,
    )
    
    # ---- BOOT SEQUENCE -----
    boot_progress = BootProgress.load(BOOT_PROGRESS_PATH)
    context.boot_progress = boot_progress
    latest_disk = boot_progress.latest_ok_disk()
    boot_disk_name = f"Disk {latest_disk}" if latest_disk is not None else "Disk 0 (recovery mode)"
    disk_context = {
        f"disk{d}_{c}": boot_progress.status(f"disk{d}_{c}")
        for d in (1, 2, 3)
        for c in (1, 2, 3)
    }

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
    
    shell_screen = ShellScreen(input_handler, screens, window, on_escape=_open_horus_menu)
    screens.push(shell_screen)
    boot_screen = BootScreen(window.buffer, frames, on_complete=_on_boot_complete, sounds=sounds)
    screens.push(boot_screen)

    window.run()