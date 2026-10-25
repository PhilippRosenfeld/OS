import logging

logger = logging.getLogger(__name__)


class Clipboard:
    """In-memory clipboard -- what Ctrl+C/X put there, Ctrl+V gets back.
    Used where there's no OS window to share a clipboard with (tests, or a
    shell without a display)."""

    def __init__(self) -> None:
        self._text = ""

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


class SystemClipboard(Clipboard):
    """The operating system's clipboard, through the pyglet window -- so
    text copied in the game can be pasted elsewhere and vice versa. Falls
    back to its in-memory copy if the OS clipboard can't be reached."""

    def __init__(self, pyglet_window) -> None:
        super().__init__()
        self._window = pyglet_window

    def get_text(self) -> str:
        try:
            return self._window.get_clipboard_text() or ""
        except Exception:
            logger.warning("could not read the system clipboard", exc_info=True)
            return super().get_text()

    def set_text(self, text: str) -> None:
        super().set_text(text)
        try:
            self._window.set_clipboard_text(text)
        except Exception:
            logger.warning("could not write the system clipboard", exc_info=True)
