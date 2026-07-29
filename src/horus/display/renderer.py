from pathlib import Path

import moderngl
import numpy as np

from .screen_buffer import ScreenBuffer
from .font_atlas import FontAtlas

SHADER_DIR = Path(__file__).parent / "shaders"



class Renderer:
    """Converts a ScreenBuffer into pixels, uploads to GPU, runs the CRT shader, and displays the result on the screen."""
    
    PLACEHOLDER_CHAR = "?"

    def __init__(self, screen_buffer: ScreenBuffer, font_atlas: FontAtlas, ctx: moderngl.Context) -> None:
        self.screen_buffer = screen_buffer
        self.font_atlas = font_atlas
        self.ctx = ctx
        pixel_width = screen_buffer.cols * font_atlas.char_width
        pixel_height = screen_buffer.rows * font_atlas.char_height
        self._pixel_buffer = np.zeros((pixel_height, pixel_width, 3), dtype=np.uint8)
        self._texture: moderngl.Texture = self.ctx.texture((pixel_width, pixel_height), 3, data=self._pixel_buffer.tobytes())
        self._program: moderngl.Program = None
        self._load_shader(str(SHADER_DIR / "crt.vert"), str(SHADER_DIR / "crt.frag"))
        self._quad: moderngl.VertexArray = None
        self._build_quad()
        self._block_cache: dict[tuple[str, tuple[int, int, int], tuple[int, int, int]], np.ndarray] = {}

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


    def _ensure_pixel_buffer_size(self) -> bool:
        """Reallocate the pixel buffer/texture if the ScreenBuffer's grid size has changed (e.g. after a window resize). Returns True if a reallocation happened."""
        pixel_width = self.screen_buffer.cols * self.font_atlas.char_width
        pixel_height = self.screen_buffer.rows * self.font_atlas.char_height
        if self._pixel_buffer.shape[1] == pixel_width and self._pixel_buffer.shape[0] == pixel_height:
            return False
        self._pixel_buffer = np.zeros((pixel_height, pixel_width, 3), dtype=np.uint8)
        self._texture.release()
        self._texture = self.ctx.texture((pixel_width, pixel_height), 3, data=self._pixel_buffer.tobytes())
        return True

    def _get_block(self, char: str, fg_color: tuple[int, int, int], bg_color: tuple[int, int, int]) -> np.ndarray:
        """Return the rendered (char_height, char_width, 3) pixel block for this glyph/color combo, computing and caching it on first use. Characters missing from the FontAtlas fall back to a placeholder glyph instead of raising."""
        if not self.font_atlas.exists_glyph(char):
            char = self.PLACEHOLDER_CHAR
        key = (char, fg_color, bg_color)
        block = self._block_cache.get(key)
        if block is None:
            glyph = self.font_atlas.get_glyph(char)
            coverage = (glyph.astype(np.float32) / 255.0)[:, :, None]
            fg = np.array(fg_color, dtype=np.float32)
            bg = np.array(bg_color, dtype=np.float32)
            block = (coverage * fg + (1.0 - coverage) * bg).astype(np.uint8)
            self._block_cache[key] = block
        return block

    def _build_pixel_buffer(self) -> None:
        """Convert the ScreenBuffer into a pixel buffer using the FontAtlas. The cursor cell (if visible)
        is drawn either as a solid foreground/background-swapped block (overwrite mode) or as a thin
        vertical bar overlaid on the normal glyph (insert mode), depending on screen_buffer.cursor_block."""
        char_width = self.font_atlas.char_width
        char_height = self.font_atlas.char_height
        cursor_visible = self.screen_buffer.cursor_visible and self.screen_buffer.view_offset == 0
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

    def render(self, window_width: int, window_height: int, margin: int = 0) -> None:
        """Full frame: rebuild pixel buffer and upload as texture only if the content or size changed,
        run the shader, draw the quad sized to preserve aspect ratio."""
        resized = self._ensure_pixel_buffer_size()
        if resized or self.screen_buffer.dirty:
            self._build_pixel_buffer()
            self._texture.write(self._pixel_buffer.tobytes())
            self.screen_buffer.dirty = False
        self._update_quad_geometry(window_width, window_height, margin)
        self._program['resolution'].value = self._display_size
        self._texture.use()
        self._quad.render(moderngl.TRIANGLE_STRIP)