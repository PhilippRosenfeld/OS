"""Generates the CPU core sprite's animation frames under assets/sprites/:
core_0.png .. core_7.png -- a chip with pins on every side and a
three-bladed rotor in the middle, each frame turned a bit further. The CPU
screen (see ui.screens.cpu_screen) cycles through them while a core is
working and shows core_0 standing still otherwise.

Three blades repeat every 120 degrees, so FRAMES frames of 120/FRAMES
degrees each loop seamlessly. Colors match the green phosphor look of
disk.png. Run from the repo root: uv run python scripts/generate_core_sprites.py
"""

import math
from pathlib import Path

import numpy as np
from PIL import Image

SPRITES_DIR = Path(__file__).resolve().parents[1] / "assets" / "sprites"
SIZE = 32
FRAMES = 8
BLADES = 3

TRANSPARENT = (0, 0, 0, 0)
PIN = (0, 154, 0, 255)
BODY = (0, 62, 0, 255)
BODY_EDGE = (0, 229, 0, 255)
BLADE = (0, 229, 0, 255)
HUB = (190, 255, 190, 255)


def _frame(rotation_deg: float) -> Image.Image:
    pixels = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    pixels[:, :] = TRANSPARENT

    # pins: 2px stubs every 4px along all four sides
    for i in range(6, SIZE - 6, 4):
        pixels[1:4, i:i + 2] = PIN
        pixels[SIZE - 4:SIZE - 1, i:i + 2] = PIN
        pixels[i:i + 2, 1:4] = PIN
        pixels[i:i + 2, SIZE - 4:SIZE - 1] = PIN

    # chip body with a bright outline
    pixels[4:SIZE - 4, 4:SIZE - 4] = BODY_EDGE
    pixels[5:SIZE - 5, 5:SIZE - 5] = BODY

    # rotor: blades are angular wedges between an inner and outer radius
    center = (SIZE - 1) / 2
    for y in range(6, SIZE - 6):
        for x in range(6, SIZE - 6):
            dx, dy = x - center, y - center
            radius = math.hypot(dx, dy)
            angle = (math.degrees(math.atan2(dy, dx)) - rotation_deg) % (360 / BLADES)
            if radius <= 2.2:
                pixels[y, x] = HUB
            elif radius <= 9.5 and angle < 38 - radius * 1.5:  # tapers towards the tip
                pixels[y, x] = BLADE
    return Image.fromarray(pixels, "RGBA")


def main() -> None:
    SPRITES_DIR.mkdir(parents=True, exist_ok=True)
    step = 360 / BLADES / FRAMES
    for i in range(FRAMES):
        _frame(i * step).save(SPRITES_DIR / f"core_{i}.png")
    print(f"wrote {FRAMES} frames to {SPRITES_DIR}")


if __name__ == "__main__":
    main()
