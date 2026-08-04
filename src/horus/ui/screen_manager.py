from horus.ui.screen import Screen


class ScreenManager:
    """Owns a stack of Screens. Only the top screen receives input --
    push()/pop() switch which one that is."""

    def __init__(self) -> None:
        self._stack: list[Screen] = []

    def push(self, screen: Screen) -> None:
        """Make `screen` the active one, on top of whatever was active before."""
        self._stack.append(screen)
        screen.on_push()

    def pop(self) -> None:
        """Deactivate the current screen and return to whatever was below it. No-op if empty."""
        if not self._stack:
            return
        screen = self._stack.pop()
        screen.on_pop()

    @property
    def active(self) -> Screen | None:
        return self._stack[-1] if self._stack else None

    def handle_text(self, text: str) -> None:
        if self.active is not None:
            self.active.handle_text(text)

    def handle_motion(self, motion: int) -> None:
        if self.active is not None:
            self.active.handle_motion(motion)

    def handle_enter(self) -> None:
        if self.active is not None:
            self.active.handle_enter()

    def handle_key(self, symbol: int, modifiers: int) -> None:
        if self.active is not None:
            self.active.handle_key(symbol, modifiers)
