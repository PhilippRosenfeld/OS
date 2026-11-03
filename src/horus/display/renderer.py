from pathlib import Path

import moderngl
import numpy as np

from .font_atlas import FontAtlas
from .screen_buffer import ScreenBuffer
from .sprite_atlas import SpriteAtlas

SHADER_DIR = Path(__file__).parent / "shaders"



class Renderer:
    """Converts a ScreenBuffer into pixels, uploads to GPU, runs the CRT shader, and displays the result on the screen."""

    PLACEHOLDER_CHAR = "?"

    def __init__(self, screen_buffer: ScreenBuffer, font_atlas: FontAtlas, ctx: moderngl.Context,
                 status_bar: ScreenBuffer | None = None, sprite_atlas: SpriteAtlas | None = None) -> None:
        """`status_bar`, if given, is a second (normally one-row) ScreenBuffer
        rendered directly below `screen_buffer`'s rows on every frame --
        outside the Screen stack entirely, so it stays on screen no matter
        which Screen is active. See display.status_bar.StatusBar.
        `sprite_atlas`, if given, resolves the names placed via
        screen_buffer.place_sprite() into pixel art composited on top of the
        glyph grid -- see _composite_sprites()."""
        self.screen_buffer = screen_buffer
        self.font_atlas = font_atlas
        self.ctx = ctx
        self.status_bar = status_bar
        self.sprite_atlas = sprite_atlas
        pixel_width = screen_buffer.cols * font_atlas.char_width
        pixel_height = self._total_rows() * font_atlas.char_height
        self._pixel_buffer = np.zeros((pixel_height, pixel_width, 3), dtype=np.uint8)
        self._texture: moderngl.Texture = self.ctx.texture((pixel_width, pixel_height), 3, data=self._pixel_buffer.tobytes())
        self._program: moderngl.Program = None
        self._load_shader(str(SHADER_DIR / "crt.vert"), str(SHADER_DIR / "crt.frag"))
        self._quad: moderngl.VertexArray = None
        self._build_quad()
        self._block_cache: dict[tuple[str, tuple[int, int, int], tuple[int, int, int]], np.ndarray] = {}
        # the inset's font at the glyph size it currently needs, and its blocks -- see _render_inset
        self._inset_font: tuple[tuple[int, int], FontAtlas, dict] | None = None

    def _load_shader(self, ver_path: str, frag_path: str) -> None:
        """Load the vertex and fragment shaders and compile them into a moderngl.Program."""
        with open(ver_path, 'r') as f:
            vertex_shader_source = f.read()
        with open(frag_path, 'r') as f:
            fragment_shader_source = f.read()
        self._program = self.ctx.program(vertex_shader=vertex_shader_source, fragment_shader=fragment_shader_source)

    def _build_quad(self) -> None:
        """Create the quad (position + UV) used to draw the pixel buffer texture. Vertex positions are rewritten each frame in _update_quad_geometry to preserve aspect ratio."""
        self._quad_vbo = self.ctx.buffer(reserve=4 * 4 * 4)
        self._quad = self.ctx.vertex_array(self._program, [(self._quad_vbo, '2f 2f', 'in_pos', 'in_uv')])

    def _update_quad_geometry(self, window_width: int, window_height: int, margin: int = 0) -> None:
        """Size the quad so the pixel buffer's aspect ratio is preserved, inset by `margin` pixels from every window edge and anchored to the top-left corner of that inset area. Slack space from the aspect mismatch collects at the right/bottom instead of stretching the content or re-centering it."""
        content_height, content_width = self._pixel_buffer.shape[:2]
        content_aspect = content_width / content_height
        window_width = max(1, window_width)
        window_height = max(1, window_height)
        avail_width = max(1, window_width - 2 * margin)
        avail_height = max(1, window_height - 2 * margin)
        avail_aspect = avail_width / avail_height
        if avail_aspect > content_aspect:
            display_height, display_width = avail_height, avail_height * content_aspect
        else:
            display_width, display_height = avail_width, avail_width / content_aspect
        left = -1.0 + 2 * margin / window_width
        top = 1.0 - 2 * margin / window_height
        right = left + 2 * display_width / window_width
        bottom = top - 2 * display_height / window_height
        vertices = np.array([
            left,  bottom, 0.0, 1.0,
            right, bottom, 1.0, 1.0,
            left,  top,    0.0, 0.0,
            right, top,    1.0, 0.0,
        ], dtype='f4')
        self._quad_vbo.write(vertices.tobytes())
        self._display_size = (display_width, display_height)


    def set_font_atlas(self, font_atlas: FontAtlas) -> None:
        """Swap in a new FontAtlas (e.g. after a font or font-size change) and drop
        cached glyph blocks, which would otherwise be the wrong pixel dimensions."""
        self.font_atlas = font_atlas
        self._block_cache = {}
        self._inset_font = None
        self.screen_buffer.dirty = True
        if self.status_bar is not None:
            self.status_bar.dirty = True

    def _total_rows(self) -> int:
        """screen_buffer's rows plus the status bar's (if any) -- the status
        bar is rendered as extra rows appended below the main content."""
        return self.screen_buffer.rows + (self.status_bar.rows if self.status_bar is not None else 0)

    def _ensure_pixel_buffer_size(self) -> bool:
        """Reallocate the pixel buffer/texture if the ScreenBuffer's grid size has changed (e.g. after a window resize). Returns True if a reallocation happened."""
        pixel_width = self.screen_buffer.cols * self.font_atlas.char_width
        pixel_height = self._total_rows() * self.font_atlas.char_height
        if self._pixel_buffer.shape[1] == pixel_width and self._pixel_buffer.shape[0] == pixel_height:
            return False
        self._pixel_buffer = np.zeros((pixel_height, pixel_width, 3), dtype=np.uint8)
        self._texture.release()
        self._texture = self.ctx.texture((pixel_width, pixel_height), 3, data=self._pixel_buffer.tobytes())
        return True

    def _get_block(self, char: str, fg_color: tuple[int, int, int], bg_color: tuple[int, int, int],
                   font_atlas: FontAtlas | None = None, cache: dict | None = None) -> np.ndarray:
        """Return the rendered (char_height, char_width, 3) pixel block for this glyph/color combo, computing and caching it on first use. Characters missing from the FontAtlas fall back to a placeholder glyph instead of raising.
        `font_atlas`/`cache` default to the main font -- the inset passes its own (see _render_inset)."""
        font_atlas = font_atlas if font_atlas is not None else self.font_atlas
        cache = cache if cache is not None else self._block_cache
        if not font_atlas.exists_glyph(char):
            char = self.PLACEHOLDER_CHAR
        key = (char, fg_color, bg_color)
        block = cache.get(key)
        if block is None:
            glyph = font_atlas.get_glyph(char)
            coverage = (glyph.astype(np.float32) / 255.0)[:, :, None]
            fg = np.array(fg_color, dtype=np.float32)
            bg = np.array(bg_color, dtype=np.float32)
            block = (coverage * fg + (1.0 - coverage) * bg).astype(np.uint8)
            cache[key] = block
        return block

    def _build_pixel_buffer(self) -> None:
        """Convert the ScreenBuffer into a pixel buffer using the FontAtlas. The cursor cell (if visible)
        is drawn either as a solid foreground/background-swapped block (overwrite mode) or as a thin
        vertical bar overlaid on the normal glyph (insert mode), depending on screen_buffer.cursor_block."""
        char_width = self.font_atlas.char_width
        char_height = self.font_atlas.char_height
        cursor_visible = self.screen_buffer.cursor_visible and self.screen_buffer.cursor_enabled and self.screen_buffer.view_offset == 0
        cursor_col = self.screen_buffer.cursor_col
        cursor_row = self.screen_buffer.cursor_row
        cursor_block = self.screen_buffer.cursor_block
        cursor_fg = self.screen_buffer.default_fg
        cursor_bg = self.screen_buffer.default_bg
        bar_width = max(1, char_width // 8)
        for row in range(self.screen_buffer.rows):
            y0 = row * char_height
            for col in range(self.screen_buffer.cols):
                cell = self.screen_buffer.get_cell(col, row)
                if cursor_visible and col == cursor_col and row == cursor_row:
                    if cursor_block:
                        block = self._get_block(cell.char, cursor_bg, cursor_fg)
                    else:
                        block = self._get_block(cell.char, cell.fg_color, cell.bg_color).copy()
                        block[:, :bar_width] = cursor_fg
                else:
                    block = self._get_block(cell.char, cell.fg_color, cell.bg_color)
                x0 = col * char_width
                self._pixel_buffer[y0:y0 + char_height, x0:x0 + char_width] = block

        if self.status_bar is not None:
            row_base = self.screen_buffer.rows
            for row in range(self.status_bar.rows):
                y0 = (row_base + row) * char_height
                for col in range(self.status_bar.cols):
                    cell = self.status_bar.get_cell(col, row)
                    block = self._get_block(cell.char, cell.fg_color, cell.bg_color)
                    x0 = col * char_width
                    self._pixel_buffer[y0:y0 + char_height, x0:x0 + char_width] = block

        self._composite_sprites()
        self._render_inset()

    def _inset_glyphs(self, char_width: int, char_height: int) -> tuple[FontAtlas, dict]:
        """The main font rasterized at the inset's glyph size -- kept as long
        as that size stays the same, since rasterizing is slow."""
        size = (char_width, char_height)
        if self._inset_font is None or self._inset_font[0] != size:
            self._inset_font = (size, FontAtlas(str(self.font_atlas.font_path), char_width, char_height), {})
        return self._inset_font[1], self._inset_font[2]

    def _render_inset(self) -> None:
        """Draws screen_buffer's inset (see ScreenBuffer.set_inset) over its
        area: its glyphs are the area's pixel size divided by the inset
        buffer's cols/rows, so a larger inset buffer shows smaller text.
        Pixels the division leaves over stay as the main grid drew them.
        Its cursor follows the inset buffer's own fields, blinking with the
        main buffer's."""
        inset = self.screen_buffer.inset
        if inset is None or inset.buffer.cols < 1 or inset.buffer.rows < 1:
            return
        source = inset.buffer
        char_width = inset.cols * self.font_atlas.char_width // source.cols
        char_height = inset.rows * self.font_atlas.char_height // source.rows
        if char_width < 1 or char_height < 1:
            return
        font_atlas, cache = self._inset_glyphs(char_width, char_height)
        x_base = inset.col * self.font_atlas.char_width
        y_base = inset.row * self.font_atlas.char_height
        buffer_height, buffer_width = self._pixel_buffer.shape[:2]
        cursor_visible = self.screen_buffer.cursor_visible and source.cursor_enabled and source.view_offset == 0
        bar_width = max(1, char_width // 8)
        for row in range(source.rows):
            y0 = y_base + row * char_height
            if y0 + char_height > buffer_height:
                break
            for col in range(source.cols):
                x0 = x_base + col * char_width
                if x0 + char_width > buffer_width:
                    break
                cell = source.get_cell(col, row)
                if cursor_visible and col == source.cursor_col and row == source.cursor_row:
                    if source.cursor_block:
                        block = self._get_block(cell.char, source.default_bg, source.default_fg, font_atlas, cache)
                    else:
                        block = self._get_block(cell.char, cell.fg_color, cell.bg_color, font_atlas, cache).copy()
                        block[:, :bar_width] = source.default_fg
                else:
                    block = self._get_block(cell.char, cell.fg_color, cell.bg_color, font_atlas, cache)
                self._pixel_buffer[y0:y0 + char_height, x0:x0 + char_width] = block

    def _sprite_scale(self) -> int:
        """Whole-number factor sprites are enlarged by, following the glyph
        size relative to the base 8x16 cell -- so a sprite covers the same
        number of grid cells at any font size (layouts can reserve space for
        it in cells), while staying pixel-crisp instead of being resampled."""
        return max(1, min(self.font_atlas.char_width // 8, self.font_atlas.char_height // 16))

    def _composite_sprites(self) -> None:
        """Alpha-blends every sprite placed via screen_buffer.place_sprite()
        on top of the glyph grid just built. Unlike a glyph block, a sprite
        keeps its own authored colors -- only its alpha channel drives the
        blend, so it isn't tinted by any cell's fg/bg. Drawn at its native
        pixel size times _sprite_scale() (see SpriteAtlas), clipped to whatever of its footprint still
        fits inside the pixel buffer; a sprite anchored (partially) outside
        the grid, or not resolvable by the atlas, is simply skipped rather
        than raising."""
        if self.sprite_atlas is None:
            return
        char_width = self.font_atlas.char_width
        char_height = self.font_atlas.char_height
        scale = self._sprite_scale()
        buffer_height, buffer_width = self._pixel_buffer.shape[:2]
        for (col, row), name in self.screen_buffer.sprites.items():
            if col < 0 or row < 0 or not self.sprite_atlas.exists(name):
                continue
            sprite = self.sprite_atlas.get(name, scale)
            x0, y0 = col * char_width, row * char_height
            if x0 >= buffer_width or y0 >= buffer_height:
                continue
            x1 = min(buffer_width, x0 + sprite.shape[1])
            y1 = min(buffer_height, y0 + sprite.shape[0])
            region = sprite[:y1 - y0, :x1 - x0]
            alpha = region[:, :, 3:4].astype(np.float32) / 255.0
            rgb = region[:, :, :3].astype(np.float32)
            dest = self._pixel_buffer[y0:y1, x0:x1].astype(np.float32)
            self._pixel_buffer[y0:y1, x0:x1] = (alpha * rgb + (1.0 - alpha) * dest).astype(np.uint8)

    def render(self, window_width: int, window_height: int, margin: int = 0) -> None:
        """Full frame: rebuild pixel buffer and upload as texture only if the content or size changed,
        run the shader, draw the quad sized to preserve aspect ratio."""
        resized = self._ensure_pixel_buffer_size()
        inset = self.screen_buffer.inset
        dirty = (self.screen_buffer.dirty or (self.status_bar is not None and self.status_bar.dirty)
                 or (inset is not None and inset.buffer.dirty))
        if resized or dirty:
            self._build_pixel_buffer()
            self._texture.write(self._pixel_buffer.tobytes())
            self.screen_buffer.dirty = False
            if inset is not None:
                inset.buffer.dirty = False
            if self.status_bar is not None:
                self.status_bar.dirty = False
        self._update_quad_geometry(window_width, window_height, margin)
        self._program['resolution'].value = self._display_size
        self._program['char_height'].value = self._display_size[1] / self._total_rows()
        self._texture.use()
        self._quad.render(moderngl.TRIANGLE_STRIP)