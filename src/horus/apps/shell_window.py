import dataclasses

from horus.apps.window import Window
from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.kernel.kernel import Kernel
from horus.kernel.registry import Registry
from horus.session.context import Context
from horus.session.history import CommandHistory
from horus.shell.input_handler import InputHandler


class ShellWindow(Window):
    """A Window whose content area is a shell of its own:

    - its own commands: `commands` (a Registry the program fills, e.g. via
      `@command(..., target=my_registry)`) plus the built-ins `help`,
      `clear` and `exit` -- the main shell's commands aren't available;
    - its own command history, prompt (see prompt()) and Tab completion
      (see complete());
    - its own Context: a copy of the main one whose screen is the shell's
      buffer, so ctx.write_line(), scrolling and prompts (incl.
      ctx.request_input) all stay inside the window.

    The shell runs on a ScreenBuffer of its own, sized to the content area,
    and is copied into the window's surface on every render -- so
    InputHandler/Context work unchanged, they just don't know the buffer
    they write to is small. `welcome` lines are printed before the first
    prompt. Everything else (frame, header, process, closing) is Window's."""

    def __init__(self, ctx: Context, title: str, commands: Registry | None = None, prompt: str = "> ",
                 welcome: list[str] | None = None, **window_options) -> None:
        super().__init__(ctx, title, **window_options)
        self._prompt = prompt
        self._welcome = welcome or []
        self.commands = self._build_commands(commands)
        self.history = CommandHistory()
        self.kernel = Kernel(registry=self.commands, bus=ctx.events if ctx.events is not None else EventBus())
        self.shell_buffer: ScreenBuffer | None = None
        self.ctx: Context | None = None
        self.input: InputHandler | None = None
        self._needs_prompt = False  # a command took the focus away before the next prompt was drawn

    @property
    def window_name(self) -> str:
        """How this window shows up in the log (see Context.window_name):
        its title, plus its process's PID if it runs as one -- so two open
        windows of the same program can be told apart."""
        return f"{self.title} (PID {self.pid})" if self.pid is not None else self.title

    # --- hooks for programs ---

    def prompt(self) -> str:
        """The shell's prompt -- override for a dynamic one (e.g. showing
        the host you're connected to)."""
        return self._prompt

    def complete(self, prefix: str) -> list[str]:
        """Tab completion candidates for the word being typed -- by default
        the program's command names."""
        return sorted(name for name in self.commands.names() if name.startswith(prefix))

    # --- lifecycle ---

    def _setup(self) -> None:
        _, _, width, height = self.content_rect
        self.shell_buffer = ScreenBuffer(width, height)
        self.shell_buffer.default_fg, self.shell_buffer.default_bg = self.surface.default_fg, self.surface.default_bg
        self.shell_buffer.clear()
        self.ctx = dataclasses.replace(self.parent_ctx, screen=self.shell_buffer, screens=self.screens,
                                       window_name=self.window_name)
        for line in self._welcome:
            self.ctx.write_line(line)
        self.input = InputHandler(self.shell_buffer, self.history, on_submit=self._submit,
                                  get_prompt=self.prompt, complete=self.complete)
        self.ctx.input_handler = self.input

    def on_resize(self) -> None:
        if self.shell_buffer is None:
            return
        _, _, width, height = self.content_rect
        self.shell_buffer.resize(width, height)
        self.shell_buffer.cursor_row = min(self.shell_buffer.cursor_row, height - 1)

    def on_resume(self) -> None:
        """A screen one of our commands opened was closed -- give the shell
        the prompt handle_enter left pending."""
        self._give_pending_prompt()

    def on_focus(self) -> None:
        """Back in focus (e.g. a command of ours had opened another window)
        -- same as on_resume."""
        self._give_pending_prompt()

    def _give_pending_prompt(self) -> None:
        if self.is_open and self._needs_prompt:
            self._needs_prompt = False
            self.input.start_line()
            self.render()

    # --- drawing ---

    def render_content(self, x: int, y: int, width: int, height: int) -> None:
        """Copies the shell's buffer into the content area -- cell by cell,
        so nothing piles up in the surface's resize replay log."""
        if self.shell_buffer is None:
            return
        for row in range(min(height, self.shell_buffer.rows)):
            for col in range(min(width, self.shell_buffer.cols)):
                source = self.shell_buffer.get_cell(col, row)
                target = self.surface.get_cell(x + col, y + row)
                target.char, target.fg_color, target.bg_color = source.char, source.fg_color, source.bg_color

    def cursor(self) -> tuple[int, int] | None:
        if self.shell_buffer is None or self.shell_buffer.view_offset != 0 or not self.shell_buffer.cursor_enabled:
            return None
        x, y, width, height = self.content_rect
        return (x + min(self.shell_buffer.cursor_col, width - 1),
                y + min(self.shell_buffer.cursor_row, height - 1))

    @property
    def cursor_block(self) -> bool:
        return self.shell_buffer.cursor_block if self.shell_buffer is not None else False

    # --- commands ---

    def _build_commands(self, commands: Registry | None) -> Registry:
        """The program's commands plus the built-ins (which a program can
        override by registering the same name itself)."""
        combined = Registry()
        if commands is not None:
            for name in commands.names():
                combined.register(name, commands.lookup(name), commands.help_text(name), commands.category(name))
        builtins = {
            "help": (self._cmd_help, "List this program's commands"),
            "clear": (self._cmd_clear, "Clear the window"),
        }
        if self.keep_running:
            builtins["exit"] = (self._cmd_exit, "Close the window -- keeps running in the background")
            builtins["quit"] = (self._cmd_quit, "Quit the program")
        else:
            builtins["exit"] = (self._cmd_exit, "Close the window")
        for name, (handler, help_text) in builtins.items():
            if combined.lookup(name) is None:
                combined.register(name, handler, help_text)
        return combined

    def _cmd_help(self, ctx: Context, argv: list[str]) -> None:
        names = sorted(self.commands.names())
        width = max(len(name) for name in names)
        for name in names:
            ctx.write_line(f"  {name:<{width}}  {self.commands.help_text(name)}")

    def _cmd_clear(self, ctx: Context, argv: list[str]) -> None:
        ctx.screen.clear()
        ctx.screen.cursor_col = ctx.screen.cursor_row = 0

    def _cmd_exit(self, ctx: Context, argv: list[str]) -> None:
        self.close()

    def _cmd_quit(self, ctx: Context, argv: list[str]) -> None:
        self.quit()

    def _submit(self, line: str) -> None:
        self.kernel.execute(line, self.ctx)

    # --- input ---

    def handle_text(self, text: str) -> None:
        self.input._handle_text(text)
        self.render()

    def handle_motion(self, motion: int) -> None:
        self.input._handle_motion(motion)
        self.render()

    def handle_enter(self) -> None:
        self.input._handle_enter()
        # a command may have closed or hidden us, opened a full screen on top,
        # or moved the focus to another window -- then the prompt waits
        if self.attached and self._host.is_active(self):
            self.input.start_line()
        elif self.is_open:
            self._needs_prompt = True
        if self.is_open:
            self.render()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if symbol in self.close_keys:
            self.close()
            return
        self.input._handle_key(symbol, modifiers)
        self.render()
