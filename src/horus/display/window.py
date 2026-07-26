import pyglet
import moderngl

from .screen_buffer import ScreenBuffer
from .font_atlas import FontAtlas
from .renderer import Renderer

class DisplayWindow:
    """Owns the pyglet window, moderngl context, and Renderer. Handles window events and rendering loop."""

    def __init__(self, font_path: str, cols: int | None = None, rows: int | None = None, title: str = "Horus", char_width: int = 8, char_height: int = 16, width: int = 1920, height: int = 1080, margin: int = 16) -> None:
        self._char_width = char_width
        self._char_height = char_height
        self._margin = margin
        if cols is None:
            cols = max(1, (width - 2 * margin) // char_width)
        if rows is None:
            rows = max(1, (height - 2 * margin) // char_height)
        self.buffer = ScreenBuffer(cols, rows)
        self._window: pyglet.window.Window = pyglet.window.Window(width=width, height=height, caption=title, resizable=True)
        self._ctx: moderngl.Context = moderngl.create_context()
        font_atlas = FontAtlas(font_path, char_width, char_height)
        self._renderer: Renderer = Renderer(self.buffer, font_atlas, self._ctx)
        self._on_key_callback = None
        self._window.push_handlers(on_draw=self._on_draw, on_resize=self._on_resize)

    def set_input_handler(self, callback) -> None:
        """Set the callback function to handle key press events."""
        self._on_key_callback = callback
        self._window.push_handlers(on_key_press=self._on_key_press)

    def _on_draw(self) -> None:
        """pyglet event handler: called every frame, triggers a render."""
        self._ctx.viewport = (0, 0, self._window.width, self._window.height)
        self._ctx.clear()
        self._renderer.render(self._window.width, self._window.height, self._margin)

    def _on_resize(self, width: int, height: int) -> None:
        """pyglet event handler: recompute the grid size so it keeps filling the window (minus the margin)."""
        cols = max(1, (width - 2 * self._margin) // self._char_width)
        rows = max(1, (height - 2 * self._margin) // self._char_height)
        self.buffer.resize(cols, rows)

    def _on_key_press(self, symbol, modifiers) -> None:
        """pyglet event handler: forwards to self._on_key_callback."""
        if self._on_key_callback is not None:
            self._on_key_callback(symbol, modifiers)

    def run(self) -> None:
        """Starts pyglet's event loop. Blocks until window is closed."""
        pyglet.app.run()