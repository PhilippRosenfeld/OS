"""Windows: programs that draw into a framed area of the screen instead of
taking it over. A Window only ever draws into its own surface (a
ScreenBuffer the size of the window, frame included) and never knows
where on screen it sits -- a host places it there, and can show several
side by side, switch the focus between them and keep the unfocused ones
updating, without the windows themselves knowing.

A host gives a window:
    open(host, width, height)   before anything else -- again to show a
                                program that ran on in the background
    update(dt)                  every refresh, focused or not
    handle_text/motion/enter/key  input, while it has the focus
    focus() / blur()            when it gains / loses the focus
    resize(width, height)       when the host re-lays it out
    on_resume()                 when a full screen one of its commands opened is closed
and reads back `surface`, `dirty` and cursor(). A host must provide
close_window(window) (the program ended), detach_window(window) (hide it,
the program keeps running), is_active(window), `screens` and `main_buffer`.
WindowManager (window_manager.py) is that host: it shows several windows
over the shell and switches the focus between them."""

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.events.types import ProcessKilledEvent
from horus.processes.process import process as Process
from horus.session.context import Context
from horus.session.user import UserRole

key = pyglet.window.key

MIN_WIDTH = 40
MIN_HEIGHT = 10


class Window:
    """A framed window: title in the top border (shown inverted while it
    has the focus), optional `header_rows` above a rule for render_header(),
    and a content area below for render_content() -- both redrawn on every
    update(). `border_color` colors the frame. Any key in `close_keys`
    closes it (pass an empty tuple for a program that needs Escape itself).

    `process_name`, if given, runs the program as a process while the
    window is open: it shows up in top/ps, set_process_load() changes what
    it uses, and killing it (kill, OOM, a memory error, ...) closes the
    window.

    `width`/`height` are the preferred size; without them a window asks
    for 3/4 of the screen (see preferred_size).

    `keep_running` makes closing (close keys, `exit`) only hide the window:
    the program -- its process and all its state, shell output, history,
    settings -- keeps running in the background, and opening it again
    (see show_app) brings that same window back. quit() really ends it, as
    does killing its process. `app_id` names it in the session's
    background_apps (see Context) so it can be found again; it defaults to
    `process_name`."""

    def __init__(self, ctx: Context, title: str, width: int | None = None, height: int | None = None,
                 header_rows: int = 0, border_color: tuple[int, int, int] | None = None,
                 close_keys: tuple[int, ...] = (key.ESCAPE,), process_name: str | None = None,
                 process_cpu_mhz: float = 5.0, process_mem_kb: int = 1024,
                 keep_running: bool = False, app_id: str | None = None) -> None:
        self.parent_ctx = ctx
        self.title = title
        self._width = width
        self._height = height
        self.header_rows = header_rows
        self.border_color = border_color
        self.close_keys = close_keys
        self._process_name = process_name
        self._process_cpu_mhz = process_cpu_mhz
        self._process_mem_kb = process_mem_kb
        self.keep_running = keep_running
        self.app_id = app_id if app_id is not None else process_name
        self.surface: ScreenBuffer | None = None
        self.dirty = True       # surface changed since the host last copied it
        self.focused = False
        self.is_open = False    # running -- shown on a host, or hidden in the background
        self.attached = False   # currently shown on a host
        self.pid: int | None = None
        self._host = None
        self._unsubscribe = None

    # --- hooks for programs ---

    def render_header(self) -> None:
        """Fills the header rows via header_write() -- called on every render."""

    def render_content(self, x: int, y: int, width: int, height: int) -> None:
        """Draws the content area (in surface coordinates) via write() --
        called on every render, after the surface was cleared."""

    def cursor(self) -> tuple[int, int] | None:
        """Where the text cursor should show, in surface coordinates -- or
        None for no cursor."""
        return None

    @property
    def cursor_block(self) -> bool:
        """Block (overwrite mode) rather than bar cursor."""
        return False

    def on_open(self) -> None:
        """Called once the window is open (surface ready, process started)."""

    def on_close(self) -> None:
        """Called once when the window closes."""

    def on_focus(self) -> None:
        """Called when the window gains the focus."""

    def on_blur(self) -> None:
        """Called when the window loses the focus."""

    def on_resume(self) -> None:
        """Called when a full screen opened from this window was closed."""

    def on_resize(self) -> None:
        """Called after resize(), before the redraw."""

    # --- geometry ---

    def preferred_size(self, cols: int, rows: int) -> tuple[int, int]:
        """The size this window wants on a cols x rows screen."""
        width = min(cols, self._width or max(MIN_WIDTH, cols * 3 // 4))
        height = min(rows, self._height or max(MIN_HEIGHT, rows * 3 // 4))
        return width, height

    @property
    def size(self) -> tuple[int, int]:
        return (self.surface.cols, self.surface.rows) if self.surface is not None else (0, 0)

    @property
    def content_rect(self) -> tuple[int, int, int, int]:
        """(x, y, width, height) of the content area within the surface."""
        width, height = self.size
        header_space = self.header_rows + 1 if self.header_rows else 0  # header rows + the rule below them
        y = 1 + header_space
        return 2, y, max(1, width - 4), max(1, height - 1 - y)

    # --- lifecycle (called by the host) ---

    def open(self, host, width: int, height: int) -> None:
        """Shows the window on `host` -- starting the program the first
        time, or bringing a program running in the background back exactly
        as it was (only re-fitted if the size changed)."""
        self._host = host
        self.attached = True
        if self.is_open:
            if self.size != (width, height):
                self.resize(width, height)
            else:
                self.render()
            return
        self.surface = self._new_surface(width, height)
        self.is_open = True
        self._start_process()
        if self.app_id is not None and self.parent_ctx.background_apps is not None:
            self.parent_ctx.background_apps[self.app_id] = self
        self._setup()
        self.on_open()
        self.render()

    def _setup(self) -> None:
        """For subclasses: build what render_content() needs, before the
        first render (see ShellWindow)."""

    def resize(self, width: int, height: int) -> None:
        self.surface = self._new_surface(width, height)
        self.on_resize()
        self.render()

    def update(self, dt: float) -> None:
        self.render()

    def focus(self) -> None:
        if not self.focused:
            self.focused = True
            self.on_focus()
            self.render()

    def blur(self) -> None:
        if self.focused:
            self.focused = False
            self.on_blur()
            self.render()

    def close(self) -> None:
        """What closing the window does: with keep_running, hide it and let
        the program run on in the background; otherwise quit()."""
        if self.keep_running and self.is_open:
            if self._host is not None and self.attached:
                self._host.detach_window(self)
            return
        self.quit()

    def quit(self) -> None:
        """Ends the program for good -- window gone, process stopped."""
        if self._host is not None and self.attached:
            self._host.close_window(self)
        else:
            self.closed()

    def detached(self) -> None:
        """The host stopped showing the window -- it keeps running in the
        background (see keep_running)."""
        self.attached = False
        self.focused = False
        self._host = None

    def closed(self) -> None:
        """The program ended -- stop its process and clean up. Safe to call
        more than once."""
        if not self.is_open:
            return
        self.is_open = False
        self.attached = False
        self.focused = False
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        apps = self.parent_ctx.background_apps
        if apps is not None and apps.get(self.app_id) is self:
            del apps[self.app_id]
        self._stop_process()
        self.on_close()

    @property
    def screens(self):
        return self._host.screens

    @property
    def main_buffer(self) -> ScreenBuffer:
        """The whole screen -- for something that opens a full screen of its own."""
        return self._host.main_buffer

    def _new_surface(self, width: int, height: int) -> ScreenBuffer:
        surface = ScreenBuffer(max(8, width), max(4, height))  # room for a frame and a line of content
        main = self.parent_ctx.screen
        if main is not None:
            surface.default_fg, surface.default_bg = main.default_fg, main.default_bg
            surface.clear()
        return surface

    # --- drawing ---

    def render(self) -> None:
        """Redraws the whole surface: frame, header, content."""
        if self.surface is None:
            return
        self.surface.clear()
        self._draw_frame()
        if self.header_rows:
            self.render_header()
        self.render_content(*self.content_rect)
        self.dirty = True

    def _draw_frame(self) -> None:
        width, height = self.size
        fg = self.border_color
        horizontal = f"+{'-' * (width - 2)}+"
        self.surface.write_string(0, 0, horizontal, fg=fg)
        for row in range(1, height - 1):
            self.surface.write_string(0, row, "|", fg=fg)
            self.surface.write_string(width - 1, row, "|", fg=fg)
        self.surface.write_string(0, height - 1, horizontal, fg=fg)
        title = f" {self.title} "[:max(0, width - 2)]  # same spot as draw_box's labels
        if self.focused:
            self.surface.write_string(1, 0, title, fg=self.surface.default_bg, bg=fg or self.surface.default_fg)
        else:
            self.surface.write_string(1, 0, title, fg=fg)
        if self.header_rows:
            self.surface.write_string(0, 1 + self.header_rows, horizontal, fg=fg)

    def write(self, col: int, row: int, text: str, fg=None, bg=None) -> None:
        """Writes into the surface, clipped to it (no wrapping)."""
        if self.surface is None or not 0 <= row < self.surface.rows or col >= self.surface.cols:
            return
        self.surface.write_string(col, row, text[:max(0, self.surface.cols - col)], fg=fg, bg=bg)

    def header_write(self, col: int, row: int, text: str, fg=None, bg=None) -> None:
        """Writes into the header rows, relative to their top-left corner
        and clipped to the inside of the frame."""
        if not 0 <= row < self.header_rows:
            return
        room = max(0, self.size[0] - 4 - col)
        self.write(2 + col, 1 + row, text[:room], fg=fg, bg=bg)

    # --- input (while focused) ---

    def handle_text(self, text: str) -> None:
        pass

    def handle_motion(self, motion: int) -> None:
        pass

    def handle_enter(self) -> None:
        pass

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol in self.close_keys:
            self.close()

    # --- process ---

    def set_process_load(self, cpu_mhz: float | None = None, mem_kb: int | None = None) -> None:
        """Changes what the program's process uses -- e.g. more CPU and
        memory while it's busy."""
        table = self.parent_ctx.process_table
        proc = table.get_process(self.pid) if table is not None and self.pid is not None else None
        if proc is None:
            return
        if cpu_mhz is not None:
            proc.baseline_cpu_mhz = proc.cpu_mhz = cpu_mhz
        if mem_kb is not None:
            proc.baseline_mem_kb = proc.mem_kb = mem_kb

    def _start_process(self) -> None:
        table = self.parent_ctx.process_table
        if self._process_name is None or table is None:
            return
        proc = table.add_process(Process(name=self._process_name, pid=0, owner=self.parent_ctx.effective_user,
                                         cpu_mhz=self._process_cpu_mhz, mem_kb=self._process_mem_kb))
        self.pid = proc.pid
        if self.parent_ctx.events is not None:
            self._unsubscribe = self.parent_ctx.events.subscribe(ProcessKilledEvent, self._on_process_killed)

    def _stop_process(self) -> None:
        table = self.parent_ctx.process_table
        if self.pid is not None and table is not None and table.get_process(self.pid) is not None:
            table.remove_process(self.pid, user=self.parent_ctx.effective_user, role=UserRole.ROOT)
        self.pid = None

    def _on_process_killed(self, event: ProcessKilledEvent) -> None:
        if event.pid == self.pid and self.is_open:
            self.pid = None  # already gone -- nothing left to remove
            self.quit()      # a killed program is over, background or not
