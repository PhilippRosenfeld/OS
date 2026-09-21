import pyglet

from horus.display.colors import NAMED_COLORS
from horus.display.screen_buffer import ScreenBuffer

LABELS = ("PWR", "TEMP", "SYS", "MSC")


class StatusBar:
    """Persistent one-row indicator strip -- PWR/TEMP/SYS/MSC, like a car's
    dashboard warning lights -- rendered by Renderer below the main screen
    content on every frame. Lives outside the Screen stack entirely (see
    DisplayWindow), so no Screen needs to know it exists; it renders blank
    (see set_visible) except while the shell itself is the active screen --
    see horus.__init__'s ScreenManager(on_active_changed=...) wiring.

    Driven by register_status_bar() (see processes.system_reactions), which
    calls set_lit() as events come in over the EventBus. TEMP and MSC have
    no real trigger yet -- they just never light up until something exists
    to drive them.

    `source_buffer`, if given, is read live on every render for its
    `default_fg` -- the *unlit* label text always tracks whatever color the
    shell itself is currently set to (see cmd_misc.color), instead of a
    fixed one. No explicit notification is needed when that color changes:
    the blinking timer alone already forces a re-render at least every
    `start_blinking(interval)` seconds, which is enough to pick it up. The
    lit background always stays amber regardless -- that's the warning-light
    color, not a themeable one. Falls back to the buffer's own default_fg
    for unlit text when no source is given (e.g. in isolation, tests)."""

    def __init__(self, cols: int, source_buffer: ScreenBuffer | None = None) -> None:
        self.buffer = ScreenBuffer(cols, 1)
        self._source_buffer = source_buffer
        self._lit = dict.fromkeys(LABELS, False)
        self._visible = False
        self._blink_on = True  # lit labels only actually show the accent color while this is True
        self._render()

    def set_lit(self, label: str, lit: bool) -> None:
        if self._lit[label] == lit:
            return
        self._lit[label] = lit
        self._render()

    def is_lit(self, label: str) -> bool:
        return self._lit[label]

    def set_visible(self, visible: bool) -> None:
        """Hidden renders as a blank row rather than not reserving the row
        at all -- keeps the screen layout/aspect ratio unaffected by which
        screen happens to be active."""
        if self._visible == visible:
            return
        self._visible = visible
        self._render()

    def is_visible(self) -> bool:
        return self._visible

    def start_blinking(self, interval: float = 0.5) -> None:
        """Makes currently (and future) lit indicators blink on/off, like a
        car's warning lights -- unlit ones are unaffected, same for the
        bar's own visibility. Mirrors DisplayWindow.start_cursor_blink().
        Call once; safe to call again after stop_blinking()."""
        pyglet.clock.schedule_interval(self._toggle_blink, interval)

    def stop_blinking(self) -> None:
        pyglet.clock.unschedule(self._toggle_blink)

    def _toggle_blink(self, dt: float) -> None:
        self._blink_on = not self._blink_on
        self._render()

    def resize(self, cols: int) -> None:
        """Keeps the status bar exactly as wide as the main screen buffer --
        called from DisplayWindow._on_resize() alongside self.buffer.resize()."""
        self.buffer.resize(cols, 1)
        self._render()

    def _render(self) -> None:
        self.buffer.clear()
        if not self._visible:
            return
        text_color = self._source_buffer.default_fg if self._source_buffer is not None else self.buffer.default_fg
        col = 0
        for label in LABELS:
            lit = self._lit[label] and self._blink_on
            text = f" {label} "
            fg = self.buffer.default_bg if lit else text_color
            bg = NAMED_COLORS["amber"] if lit else self.buffer.default_bg
            self.buffer.write_string(col, 0, text, fg=fg, bg=bg)
            col += len(text) + 1  # 1-cell gap between lights
