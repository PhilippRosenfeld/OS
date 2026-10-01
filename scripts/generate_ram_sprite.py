"""Generates assets/sprites/ram.png -- a RAM module (green PCB, a row of
memory chips, gold-ish contact pins along the bottom edge with the key
notch) for the RAM screen (see ui.screens.ram_screen). 32x16 px, i.e. 4x1
cells at the base 8x16 glyph size. Colors match the green phosphor look of
disk.png/core_*.png. Run from the repo root:
uv run python scripts/generate_ram_sprite.py
"""

from pathlib import Path

import numpy as np
from PIL import Image

SPRITES_DIR = Path(__file__).resolve().parents[1] / "assets" / "sprites"
WIDTH, HEIGHT = 32, 16

TRANSPARENT = (0, 0, 0, 0)
PCB = (0, 62, 0, 255)
PCB_EDGE = (0, 154, 0, 255)
CHIP = (0, 229, 0, 255)
CHIP_MARK = (0, 108, 0, 255)
PIN = (190, 255, 190, 255)


def main() -> None:
    pixels = np.zeros((HEIGHT, WIDTH, 4), dtype=np.uint8)
    pixels[:, :] = TRANSPARENT

    # board with a bright outline, leaving room for the pins below
    pixels[2:13, 0:WIDTH] = PCB_EDGE
    pixels[3:12, 1:WIDTH - 1] = PCB

    # four memory chips with a dot marking pin 1
    for x in (3, 10, 17, 24):
        pixels[4:10, x:x + 5] = CHIP
        pixels[5, x + 1] = CHIP_MARK

    # contact pins along the bottom edge, with the key notch off-center
    for x in range(1, WIDTH - 1, 2):
        if x in (11, 13):
            continue
        pixels[13:15, x] = PIN

    SPRITES_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, "RGBA").save(SPRITES_DIR / "ram.png")
    print(f"wrote {SPRITES_DIR / 'ram.png'}")


if __name__ == "__main__":
    main()
