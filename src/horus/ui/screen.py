from abc import ABC, abstractmethod


class Screen(ABC):
    """Base for anything that owns the keyboard and draws into the ScreenBuffer
    while it's active: the shell, a settings menu, a start screen, etc.
    Only the top of the ScreenManager's stack receives these calls."""

    def on_push(self) -> None:
        """Called once when this screen becomes active (pushed onto the stack)."""

    def on_pop(self) -> None:
        """Called once when this screen stops being active (popped off the stack)."""

    def on_resume(self) -> None:
        """Called when this screen becomes active again because the screen above
        it was popped off (as opposed to being pushed fresh -- see on_push)."""

    @abstractmethod
    def handle_text(self, text: str) -> None:
        pass

    @abstractmethod
    def handle_motion(self, motion: int) -> None:
        pass

    @abstractmethod
    def handle_enter(self) -> None:
        pass

    @abstractmethod
    def handle_key(self, symbol: int, modifiers: int) -> None:
        pass
