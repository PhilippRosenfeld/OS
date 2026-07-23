import numpy as np
from PIL import Image, ImageDraw, ImageFont

class FontAtlas:
    """Rasterizes a font into a texture atlas and provides glyph metrics for rendering text."""

    def __init__(self, font_path: str, char_width: int, char_height: int) -> None:
        self.font_path = font_path
        self.char_width = char_width
        self.char_height = char_height
        self.glyphs: dict[str, np.ndarray] = {}
        self._rasterize_all_glyphs(font_path)

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
