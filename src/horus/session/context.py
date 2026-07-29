from dataclasses import dataclass, field

from horus.events.bus import EventBus
from horus.filesystem.vfs import VFS
from horus.display.screen_buffer import ScreenBuffer

@dataclass
class Context:
    """Bundles everything a command needs to execute: who's running it,
    where they are, and what systems they can reach. Passed into every
    command handler as the first argument."""
    
    session_id: str
    user: str
    cwd: str
    env: dict[str, str] = field(default_factory=dict)
    
    fs: VFS = None
    events: EventBus = None
    screen: ScreenBuffer = None
            
    def resolve_path(self, path: str) -> str:
        """Resolve a path relative to the current working directory."""
        if self.fs is None:
            raise RuntimeError("Filesystem not set in context")
        return self.fs.resolve_path(self.cwd, path)

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