from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..paths import FONTS_DIR


class FontAtlas:
    """Rasterizes a font into a texture atlas and provides glyph metrics for rendering text."""

    def __init__(self, font_path: str, char_width: int, char_height: int) -> None:
        self.font_path = self._resolve_font_path(font_path)
        self.char_width = char_width
        self.char_height = char_height
        self.glyphs: dict[str, np.ndarray] = {}
        self._rasterize_all_glyphs(str(self.font_path))

    @staticmethod
    def _resolve_font_path(font_path: str) -> Path:
        """Resolve font_path directly, or as a filename inside FONTS_DIR."""
        path = Path(font_path)
        if path.is_file():
            return path
        candidate = FONTS_DIR / font_path
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"Font '{font_path}' not found directly or in {FONTS_DIR}")

    def _rasterize_all_glyphs(self, font_path: str) -> None:
        """Render every printable ASCII character into a texture atlas and store their metrics."""
        font = ImageFont.truetype(font_path, size=self.char_height)
        for code in range(32, 127):
            char = chr(code)
            image = Image.new("L", (self.char_width, self.char_height), color=0)
            draw = ImageDraw.Draw(image)
            draw.text((0, 0), char, font=font, fill=255)
            self.glyphs[char] = np.array(image, dtype=np.uint8)

    def get_glyph(self, char: str) -> np.ndarray:
        """Return the rasterized glyph for the given character."""
        if char not in self.glyphs:
            raise ValueError(f"Glyph for character '{char}' not found in atlas.")
        return self.glyphs[char]
    
    def exists_glyph(self, char: str) -> bool:
        """Checks if a registered glyph exists for the given character."""
        if char in self.glyphs:
            return True
        else: 
            return False
    
class FontRegistry:
    """Holds multiple named FontAtlas instances. The active one is used
    by the renderer; others are available for boot logos, UI accents,
    or a future 'font' command that lets the player customize the look."""

    def __init__(self) -> None:
        self._atlases: dict[str, FontAtlas] = {}
        self._active: str | None = None

    def register(self, name: str, atlas: FontAtlas) -> None:
        """Add a FontAtlas under the given name. The first registered font becomes active."""
        self._atlases[name] = atlas
        if self._active is None:
            self._active = name

    def set_active(self, name: str) -> None:
        """Switch the active font to the given registered name."""
        if name not in self._atlases:
            raise ValueError(f"Font '{name}' is not registered.")
        self._active = name

    def active(self) -> FontAtlas:
        """Return the currently active FontAtlas."""
        if self._active is None:
            raise ValueError("No font is registered.")
        return self._atlases[self._active]

    def get(self, name: str) -> FontAtlas:
        """Return the FontAtlas registered under the given name."""
        if name not in self._atlases:
            raise ValueError(f"Font '{name}' is not registered.")
        return self._atlases[name]
