from pathlib import Path

import moderngl
import numpy as np

from .screen_buffer import ScreenBuffer
from .font_atlas import FontAtlas

SHADER_DIR = Path(__file__).parent / "shaders"


class Renderer:
    """Converts a ScreenBuffer into pixels, uploads to GPU, runs the CRT shader, and displays the result on the screen."""

    def __init__(self, screen_buffer: ScreenBuffer, font_atlas: FontAtlas, ctx: moderngl.Context) -> None:
        self.screen_buffer = screen_buffer
        self.font_atlas = font_atlas
        self.ctx = ctx
        pixel_width = screen_buffer.cols * font_atlas.char_width
        pixel_height = screen_buffer.rows * font_atlas.char_height
        self._pixel_buffer = np.zeros((pixel_height, pixel_width, 3), dtype=np.uint8)
        self._texture: moderngl.Texture = moderngl.Texture((pixel_width, pixel_height), 3, data=self._pixel_buffer.tobytes())
        self._program: moderngl.Program = None
        self._load_shader(str(SHADER_DIR / "crt.vert"), str(SHADER_DIR / "crt.frag"))
        self._quad: moderngl.VertexArray = None
        self._build_quad()

    def _load_shader(self, ver_path: str, frag_path: str) -> None:
        """Load the vertex and fragment shaders and compile them into a moderngl.Program."""
        with open(ver_path, 'r') as f:
            vertex_shader_source = f.read()
        with open(frag_path, 'r') as f:
            fragment_shader_source = f.read()
        self._program = self.ctx.program(vertex_shader=vertex_shader_source, fragment_shader=fragment_shader_source)

    def _build_quad(self) -> None:
        """Create the fullscreen quad (position + UV) used to draw the pixel buffer texture."""
        vertices = np.array([
            -1.0, -1.0, 0.0, 1.0,
             1.0, -1.0, 1.0, 1.0,
            -1.0,  1.0, 0.0, 0.0,
             1.0,  1.0, 1.0, 0.0,
        ], dtype='f4')
        vbo = self.ctx.buffer(vertices.tobytes())
        self._quad = self.ctx.vertex_array(self._program, [(vbo, '2f 2f', 'in_pos', 'in_uv')])
        
    def _build_pixel_buffer(self) -> None:
        """Convert the ScreenBuffer into a pixel buffer using the FontAtlas."""
        char_width = self.font_atlas.char_width
        char_height = self.font_atlas.char_height
        for row in range(self.screen_buffer.rows):
            for col in range(self.screen_buffer.cols):
                cell = self.screen_buffer.get_cell(col, row)
                glyph = self.font_atlas.get_glyph(cell.char)
                coverage = (glyph.astype(np.float32) / 255.0)[:, :, None]
                fg = np.array(cell.fg_color, dtype=np.float32)
                bg = np.array(cell.bg_color, dtype=np.float32)
                block = coverage * fg + (1.0 - coverage) * bg
                y0 = row * char_height
                x0 = col * char_width
                self._pixel_buffer[y0:y0 + char_height, x0:x0 + char_width] = block.astype(np.uint8)
                
    def render(self) -> None:
        """Full frame: rebuild pixel buffer, upload as texture,
        run the shader, draw the fullscreen quad."""
        self._build_pixel_buffer()
        self._texture.write(self._pixel_buffer.tobytes())
        self._texture.use()
        self._program.use()
        self._quad.render()