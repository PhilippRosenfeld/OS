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
        self._on_text_callback = None
        self._on_motion_callback = None
        self._on_enter_callback = None
        self._window.push_handlers(on_draw=self._on_draw, on_resize=self._on_resize)

    def set_input_handler(self, callback) -> None:
        """Set the callback function to handle key press events."""
        self._on_key_callback = callback
        self._window.push_handlers(on_key_press=self._on_key_press)

    def set_text_handler(self, on_text=None, on_motion=None, on_enter=None) -> None:
        """Register callbacks for text input: on_text(str) for typed characters,
        on_motion(motion) for cursor/backspace motions (see pyglet.window.key.MOTION_*),
        on_enter() when Enter/Return is pressed."""
        self._on_text_callback = on_text
        self._on_motion_callback = on_motion
        self._on_enter_callback = on_enter
        self._window.push_handlers(
            on_text=self._on_text,
            on_text_motion=self._on_text_motion,
            on_key_press=self._on_enter_key,
        )

    def start_cursor_blink(self, interval: float = 0.5) -> None:
        """Toggle the ScreenBuffer's cursor visibility on a timer, making it blink."""
        def toggle(dt: float) -> None:
            self.buffer.cursor_visible = not self.buffer.cursor_visible
            self.buffer.dirty = True
        pyglet.clock.schedule_interval(toggle, interval)

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

    def _on_text(self, text: str) -> None:
        """pyglet event handler: forwards typed text to self._on_text_callback."""
        if self._on_text_callback is not None:
            self._on_text_callback(text)

    def _on_text_motion(self, motion: int) -> None:
        """pyglet event handler: forwards cursor/backspace motions to self._on_motion_callback."""
        if self._on_motion_callback is not None:
            self._on_motion_callback(motion)

    def _on_enter_key(self, symbol: int, modifiers: int) -> None:
        """pyglet event handler: fires self._on_enter_callback when Enter/Return is pressed."""
        if symbol == pyglet.window.key.ENTER and self._on_enter_callback is not None:
            self._on_enter_callback()

    def run(self) -> None:
        """Starts pyglet's event loop. Blocks until window is closed."""
        pyglet.app.run()