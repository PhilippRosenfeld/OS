class CommandHistory:

    def __init__(self, max_size: int = 500) -> None:
        self._entries: list[str] = []
        self._max_size = max_size
        self._cursor: int | None = None   #None = currently not browsing
        self._draft: str = "" #In Progress line, saved when browsing starts

    def add(self, line: str) -> None:
        if not line.strip():
            return
        if self._entries and self._entries[-1] == line:
            return

        self._entries.append(line)

        if len(self._entries) > self._max_size:
            self._entries.pop(0)  # evict the oldest entry, not the one just added

        self._cursor = None

    def previous(self, current_draft: str) -> None:
        """Move one step further into the past. current_draft is what
        the user was typing before starting to browse (saved on first
        call so it can be restored via next()). Returns None if there's
        no further history to go back to."""

        if self._entries is None:
            return None

        if self._cursor is None:
            self._draft = current_draft
            self._cursor = len(self._entries)

        if self._cursor == 0:
            return None

        self._cursor -= 1

        return self._entries[self._cursor]

    def next(self) -> None:
        """Move one step back toward the present. Returns the saved
        draft once you move past the newest entry, or None if not
        currently browsing at all."""

        if self._cursor is None:
            return None

        self._cursor += 1

        if self._cursor >= len(self._entries):
            self._cursor = None
            return self._draft

        return self._entries[self._cursor]

    def all(self) -> list[str]:
        """Returns full history, oldest first."""

        return list(self._entries)
        