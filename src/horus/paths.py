from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
SHADERS_DIR = ASSETS_DIR / "shaders"
SOUNDS_DIR = ASSETS_DIR / "sounds"
BOOT_SOUNDS_DIR = SOUNDS_DIR / "hardware" / "booting"
DATA_DIR = PROJECT_ROOT / "data"
BOOT_DIR = DATA_DIR / "boot"
SAVES_DIR = PROJECT_ROOT / "saves"
BOOT_PROGRESS_PATH = SAVES_DIR / "boot_progress.json"
HARDWARE_SPEC_PATH = SAVES_DIR / "hardware.json"