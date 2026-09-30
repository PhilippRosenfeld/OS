from pathlib import Path

import numpy as np
from PIL import Image

from ..paths import SPRITES_DIR


class SpriteAtlas:
    """Loads pixel-art sprites (e.g. hardware icons) as RGBA arrays, cached
    by name. Unlike FontAtlas glyphs -- which are recolored per fg/bg at
    draw time -- sprites carry their own fixed colors; only their alpha
    channel is used for blending onto the pixel buffer (see
    Renderer._composite_sprites()), so a drive icon doesn't get tinted by
    whatever text colors happen to be active nearby. Sprites are never
    resampled (which would blur pixel art) -- only enlarged by a whole
    factor (see get()'s `scale`), which the Renderer ties to the glyph size
    so a sprite keeps covering the same grid cells at every font size; use
    cell_span() to know how many cells a sprite's native size covers at a
    given char size."""

    def __init__(self, sprites_dir: str | Path = SPRITES_DIR) -> None:
        self._sprites_dir = Path(sprites_dir)
        self._cache: dict[str, np.ndarray] = {}
        self._scaled_cache: dict[tuple[str, int], np.ndarray] = {}

    def _resolve_path(self, name: str) -> Path:
        """Resolve name directly, or as a filename (with .png implied) inside sprites_dir."""
        path = Path(name)
        if path.is_file():
            return path
        candidate = self._sprites_dir / f"{name}.png"
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"Sprite '{name}' not found in {self._sprites_dir}")

    def get(self, name: str, scale: int = 1) -> np.ndarray:
        """Returns the (H, W, 4) RGBA pixel array for this sprite, loading and
        caching it on first use. `scale` > 1 enlarges it by that whole factor
        (every pixel becomes a scale x scale block, so pixel art stays crisp) --
        see Renderer._sprite_scale for how that follows the glyph size."""
        block = self._cache.get(name)
        if block is None:
            image = Image.open(self._resolve_path(name)).convert("RGBA")
            block = np.array(image, dtype=np.uint8)
            self._cache[name] = block
        if scale <= 1:
            return block
        scaled = self._scaled_cache.get((name, scale))
        if scaled is None:
            scaled = np.repeat(np.repeat(block, scale, axis=0), scale, axis=1)
            self._scaled_cache[(name, scale)] = scaled
        return scaled

    def exists(self, name: str) -> bool:
        """Checks if a sprite by this name can be loaded, without raising."""
        if name in self._cache:
            return True
        try:
            self._resolve_path(name)
            return True
        except FileNotFoundError:
            return False

    def cell_span(self, name: str, char_width: int, char_height: int) -> tuple[int, int]:
        """How many (cols, rows) this sprite's native pixel size covers at
        the given char cell size, rounded up -- lets a caller reserve grid
        space for a sprite without overlapping other content."""
        height, width = self.get(name).shape[:2]
        return -(-width // char_width), -(-height // char_height)
