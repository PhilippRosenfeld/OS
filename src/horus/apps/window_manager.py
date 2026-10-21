import pyglet

from horus.apps.window import Window
from horus.display.screen_buffer import ScreenBuffer
from horus.ui.screen import Screen
from horus.ui.screen_manager import ScreenManager

key = pyglet.window.key

_CASCADE = (2, 1)  # how far each further window is offset from the previous one


def is_switch_key(symbol: int, modifiers: int) -> bool:
    """Ctrl+Alt pressed: the left Alt while Ctrl is held, or Ctrl while Alt
    is held. The right Alt never counts -- on Windows AltGr arrives as
    Ctrl+right Alt, and typing e.g. '@' (AltGr+Q) must not switch windows."""
    if symbol == key.LALT:
        return bool(modifiers & key.MOD_CTRL)
    if symbol in (key.LCTRL, key.RCTRL):
        return bool(modifiers & key.MOD_ALT)
    return False


class WindowManager(Screen):
    """Shows windows (see apps.window) over the screen that was active
    before -- normally the main shell, the "desktop" -- and lets the user
    switch the focus between the shell and every window with Ctrl+Alt
    (Ctrl+Alt+Shift goes backwards).

    Everything keeps running side by side: the shell writes into the main
    buffer as always, every window draws into its own surface, and every
    window is updated on each tick whether it has the focus or not. What's
    actually shown is composited into a separate `display` buffer: the
    shell, and -- unless the shell itself has the focus, which shows it
    unobstructed -- the windows on top of it, the focused one frontmost.
    The app swaps the renderer over to `display` while this screen is active
    (see DisplayWindow.show_buffer), so windows never overwrite the shell's
    own content.

    Input goes to whatever has the focus: a window, or the screen
    underneath (`base`), forwarded as is. Closing the last window, or a
    background program's last window being hidden (see
    Window.keep_running), takes the manager down again.

    Open windows with show_window()/show_app() rather than directly."""

    def __init__(self, buffer: ScreenBuffer, screens: ScreenManager, base: Screen | None,
                 refresh_interval: float = 0.1) -> None:
        self._buffer = buffer
        self._screens = screens
        self.base = base
        self._refresh_interval = refresh_interval
        self.display = ScreenBuffer(buffer.cols, buffer.rows)
        self.windows: list[Window] = []          # in opening order -- the Ctrl+Alt cycle order
        self._z_order: list[Window] = []         # back to front
        self._positions: dict[int, tuple[int, int]] = {}
        self.focused: Window | None = None       # None: the base screen (the shell) has the focus
        self._layout_size = (buffer.cols, buffer.rows)

    # --- host interface (see apps.window) ---

    @property
    def screens(self) -> ScreenManager:
        return self._screens

    @property
    def main_buffer(self) -> ScreenBuffer:
        return self._buffer

    def is_active(self, window: Window) -> bool:
        return self._screens.active is self and self.focused is window

    def close_window(self, window: Window) -> None:
        """The program ended -- take its window away for good."""
        self._remove(window)
        window.closed()
        self._after_removal()

    def detach_window(self, window: Window) -> None:
        """Hide the window; its program keeps running in the background."""
        self._remove(window)
        window.detached()
        self._after_removal()

    # --- windows ---

    def open_window(self, window: Window) -> None:
        """Shows `window` (new, or running in the background) and focuses it.
        Already shown here: just focuses it."""
        if window in self.windows:
            self.focus(window)
            return
        width, height = window.preferred_size(self._buffer.cols, self._buffer.rows)
        self._positions[id(window)] = self._cascade_position(width, height, len(self.windows))
        self.windows.append(window)
        self._z_order.append(window)
        window.open(self, width, height)
        self.focus(window)

    def position_of(self, window: Window) -> tuple[int, int]:
        return self._positions[id(window)]

    def _cascade_position(self, width: int, height: int, index: int) -> tuple[int, int]:
        """Centered for the first window, each further one cascaded a bit
        down and right -- starting over once it would run off screen."""
        cols, rows = self._buffer.cols, self._buffer.rows
        x, y = (cols - width) // 2, (rows - height) // 2
        dx, dy = _CASCADE
        fits = 1 + min((cols - width - x) // dx, (rows - height - y) // dy)
        steps = index % max(1, fits)
        return x + dx * steps, y + dy * steps

    def _remove(self, window: Window) -> None:
        if window not in self.windows:
            return
        index = self.windows.index(window)
        self.windows.remove(window)
        self._z_order.remove(window)
        self._positions.pop(id(window), None)
        if self.focused is window:
            self.focused = None
            # the next window in line takes over, or back to the shell
            if self.windows:
                self.focus(self.windows[min(index, len(self.windows)) - 1])
            else:
                self.focus(None)

    def _after_removal(self) -> None:
        if not self.windows and self._screens.active is self:
            self._screens.pop()
        else:
            self._composite()

    # --- focus ---

    def focus(self, target: Window | None) -> None:
        """Gives the focus to a window, or with None to the base screen."""
        if self.focused is not None and self.focused is not target:
            self.focused.blur()
        self.focused = target
        if target is None:
            if self.base is not None and self._screens.active is self:
                self.base.on_resume()  # e.g. the shell draws a prompt it still owes
        else:
            self._z_order.remove(target)
            self._z_order.append(target)
            target.focus()
        self._composite()

    def focus_next(self, step: int = 1) -> None:
        """Cycles the focus: shell, then every window in opening order."""
        cycle: list[Window | None] = [None, *self.windows]
        index = cycle.index(self.focused) if self.focused in cycle else 0
        self.focus(cycle[(index + step) % len(cycle)])

    # --- lifecycle ---

    def on_push(self) -> None:
        self._composite()
        pyglet.clock.schedule_interval(self._tick, self._refresh_interval)

    def on_pop(self) -> None:
        pyglet.clock.unschedule(self._tick)
        for window in list(self.windows):
            self._remove(window)
            if window.keep_running:
                window.detached()
            else:
                window.closed()
        self._buffer.dirty = True  # the renderer goes back to showing the main buffer

    def on_resume(self) -> None:
        """A full screen opened from here was closed -- whatever has the
        focus gets to redraw what it owes (e.g. a prompt). Windows that were
        closed meanwhile (e.g. their process got killed) may have left us
        empty."""
        if not self.windows:
            self._screens.pop()
            return
        if self.focused is None:
            if self.base is not None:
                self.base.on_resume()
        else:
            self.focused.on_resume()
        self._composite()

    def _tick(self, dt: float) -> None:
        if self._screens.active is not self:
            return
        if (self._buffer.cols, self._buffer.rows) != self._layout_size:
            self._relayout()
        for window in list(self.windows):
            window.update(dt)
        self._composite()

    def _relayout(self) -> None:
        """The grid changed size -- re-fit every window and re-place them."""
        self._layout_size = (self._buffer.cols, self._buffer.rows)
        for index, window in enumerate(self.windows):
            width, height = window.preferred_size(*self._layout_size)
            self._positions[id(window)] = self._cascade_position(width, height, index)
            window.resize(width, height)

    # --- compositing ---

    def _composite(self) -> None:
        """The shell, then -- unless the shell has the focus -- every
        window back to front, into `display`; the cursor comes from
        whatever has the focus."""
        if (self.display.cols, self.display.rows) != (self._buffer.cols, self._buffer.rows):
            self.display = ScreenBuffer(self._buffer.cols, self._buffer.rows)
        for row in range(self._buffer.rows):
            for col in range(self._buffer.cols):
                self._copy_cell(self._buffer.get_cell(col, row), col, row)

        source = self._buffer
        if self.focused is not None:
            for window in self._z_order:
                self._blit(window)
            cursor = self.focused.cursor()
            self.display.cursor_enabled = cursor is not None
            if cursor is not None:
                left, top = self.position_of(self.focused)
                self.display.cursor_col, self.display.cursor_row = left + cursor[0], top + cursor[1]
                self.display.cursor_block = self.focused.cursor_block
        else:
            self.display.cursor_enabled = source.cursor_enabled
            self.display.cursor_col, self.display.cursor_row = source.cursor_col, source.cursor_row
            self.display.cursor_block = source.cursor_block
        self.display.cursor_visible = source.cursor_visible  # the app's blink timer drives the main buffer's
        self.display.dirty = True

    def _blit(self, window: Window) -> None:
        surface = window.surface
        if surface is None:
            return
        left, top = self.position_of(window)
        for row in range(surface.rows):
            for col in range(surface.cols):
                if 0 <= left + col < self.display.cols and 0 <= top + row < self.display.rows:
                    self._copy_cell(surface.get_cell(col, row), left + col, top + row)
        window.dirty = False

    def _copy_cell(self, source, col: int, row: int) -> None:
        target = self.display.get_cell(col, row)
        target.char, target.fg_color, target.bg_color = source.char, source.fg_color, source.bg_color

    # --- input ---

    def _target(self):
        return self.focused if self.focused is not None else self.base

    def _after_input(self) -> None:
        if self._screens.active is self:
            self._composite()

    def handle_text(self, text: str) -> None:
        target = self._target()
        if target is not None:
            target.handle_text(text)
        self._after_input()

    def handle_motion(self, motion: int) -> None:
        target = self._target()
        if target is not None:
            target.handle_motion(motion)
        self._after_input()

    def handle_enter(self) -> None:
        target = self._target()
        if target is not None:
            target.handle_enter()
        self._after_input()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if is_switch_key(symbol, modifiers):
            self.focus_next(-1 if modifiers & key.MOD_SHIFT else 1)
            return
        target = self._target()
        if target is not None:
            target.handle_key(symbol, modifiers)
        self._after_input()


def show_window(ctx, window: Window) -> WindowManager:
    """Shows `window` and gives it the focus -- in the WindowManager that's
    already up, or in a new one over the current screen (normally the
    shell). What a command that starts a windowed program calls."""
    active = ctx.screens.active
    if isinstance(active, WindowManager):
        manager = active
    else:
        manager = WindowManager(ctx.screen, ctx.screens, base=active)
        ctx.screens.push(manager)
    manager.open_window(window)
    return manager


def show_app(ctx, app_id: str, create) -> WindowManager:
    """Shows the program `app_id` if it's still running (in the background,
    see Window.keep_running) -- with everything as it was left -- or starts
    it with `create()`:

        show_app(ctx, "netman", lambda: NetmanWindow(ctx))
    """
    window = ctx.background_apps.get(app_id) if ctx.background_apps is not None else None
    if window is None or not window.is_open:
        window = create()
    return show_window(ctx, window)
