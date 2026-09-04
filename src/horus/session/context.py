from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from horus.display.screen_buffer import ScreenBuffer
from horus.display.window import DisplayWindow
from horus.events.bus import EventBus
from horus.filesystem.vfs import VFS
from horus.processes.processTable import ProcessTable
from horus.session.user import UserRole
from horus.ui.screen_manager import ScreenManager

if TYPE_CHECKING:
    # deferred to avoid circular imports at runtime -- these modules import
    # (directly or transitively) back into session/kernel code that depends
    # on Context, so only a type checker (never actual execution) sees them
    from horus.audio.sound_manager import SoundManager
    from horus.kernel.kernel import Kernel
    from horus.session.user import UserRegistry
    from horus.shell.input_handler import InputHandler
    from horus.ui.main_menu_screen import MainMenuScreen


@dataclass
class Context:
    """Bundles everything a command needs to execute: who's running it,
    where they are, and what systems they can reach. Passed into every
    command handler as the first argument."""

    session_id: str
    user: str #logged in user, stable for the session
    cwd: str
    env: dict[str, str] = field(default_factory=dict)

    fs: VFS = None
    events: EventBus = None
    sounds: "SoundManager" = None
    screen: ScreenBuffer = None
    screens: ScreenManager = None
    users: "UserRegistry" = None
    kernel: "Kernel" = None
    window: DisplayWindow = None
    effective_user: str = None    #user that executes command, defaults to user
    input_handler: "InputHandler" = None
    main_menu: "MainMenuScreen" = None
    process_table: "ProcessTable" = None


    def __post_init__(self):
        if self.effective_user is None:
            self.effective_user = self.user
            
    @property
    def effective_role(self) -> UserRole:
        """Resolves the effective user's role for permission checks that need
        it (e.g. encrypt/decrypt, kill -- see filesystem.permissions and
        ProcessTable.remove_process). Defaults to the least-privileged role
        if there's no UserRegistry on this context or the user isn't
        registered in it, so an unusual setup fails closed rather than open."""
        if self.users is None:
            return UserRole.USER
        user = self.users.get(self.effective_user)
        return user.role if user is not None else UserRole.USER

    def resolve_path(self, path: str) -> str:
        """Resolve a path relative to the current working directory."""
        if self.fs is None:
            raise RuntimeError("Filesystem not set in context")
        return self.fs.resolve_path(cwd=self.cwd, path=path)

    def write_line(self, text: str, fg=None, bg=None) -> None:
        """Writes text at column 0 of the current output row. Multi-line input
        (containing '\\n') is split and written as separate lines, since the
        screen buffer has no concept of a newline character -- only rows."""
        for line in text.split("\n"):
            self._write_single_line(line, fg, bg)

    def _write_single_line(self, text: str, fg=None, bg=None) -> None:
        cols = self.screen.cols
        lines_needed = max(1, -(-len(text) // cols))
        last_row = self.screen.rows - 1

        end_row = self.screen.cursor_row + lines_needed - 1  # last row this write will actually touch
        if end_row > last_row:
            overflow = end_row - last_row
            self.screen.scroll(direction='u', lines=overflow)
            self.screen.cursor_row -= overflow

        self.screen.write_string(col=0, row=self.screen.cursor_row, string=text, fg=fg, bg=bg)

        new_row = self.screen.cursor_row + lines_needed
        if new_row > last_row:  # no fresh row left below the output -- scroll to make one
            self.screen.scroll(direction='u', lines=new_row - last_row)
            new_row = last_row
        self.screen.cursor_row = new_row
        self.screen.cursor_col = 0

    def request_input(self, callback: Callable[[str], None], masked: bool = False) -> None:
        if self.input_handler is None:
            raise RuntimeError("no input handler available on this context")
        self.input_handler.request_line(callback, masked=masked)