from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # OS/ Ordner
ASSETS_DIR = PROJECT_ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
SHADERS_DIR = ASSETS_DIR / "shaders"
DATA_DIR = PROJECT_ROOT / "data"
BOOT_DIR = DATA_DIR / "boot"
SAVES_DIR = PROJECT_ROOT / "saves"