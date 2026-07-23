import pyglet
import moderngl

from .screen_buffer import ScreenBuffer
from .font_atlas import FontAtlas
from .renderer import Renderer

class DisplayWindow:
    """Owns the pyglet window, moderngl context, and Renderer. Handles window events and rendering loop."""

    def __init__(self, font_path: str, cols: int = 80, rows: int = 25, title: str = "Horus", char_width: int = 8, char_height: int = 16) -> None:
        self.buffer = ScreenBuffer(cols, rows)
        self._window: pyglet.window.Window = pyglet.window.Window(width=cols * char_width, height=rows * char_height, caption=title, resizable=True)
        self._ctx: moderngl.Context = moderngl.create_context()
        font_atlas = FontAtlas(font_path, char_width, char_height)
        self._renderer: Renderer = Renderer(self.buffer, font_atlas, self._ctx)
        self._on_key_callback = None
        self._window.push_handlers(on_draw=self._on_draw)

    def set_input_handler(self, callback) -> None:
        """Set the callback function to handle key press events."""
        self._on_key_callback = callback
        self._window.push_handlers(on_key_press=self._on_key_press)

    def _on_draw(self) -> None:
        """pyglet event handler: called every frame, triggers a render."""
        self._ctx.clear()
        self._renderer.render()

    def _on_key_press(self, symbol, modifiers) -> None:
        """pyglet event handler: forwards to self._on_key_callback."""
        if self._on_key_callback is not None:
            self._on_key_callback(symbol, modifiers)

    def run(self) -> None:
        """Starts pyglet's event loop. Blocks until window is closed."""
        pyglet.app.run()