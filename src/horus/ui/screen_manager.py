from typing import Callable

from horus.ui.screen import Screen


class ScreenManager:
    """Owns a stack of Screens. Only the top screen receives input --
    push()/pop()/replace() switch which one that is."""

    def __init__(self, on_active_changed: Callable[["Screen | None"], None] | None = None) -> None:
        self._stack: list[Screen] = []
        self._on_active_changed = on_active_changed  # notified (with the new self.active) whenever
                                                       # push()/pop()/replace() change what's on top --
                                                       # e.g. so the status bar can show only while the
                                                       # active screen is the shell (see horus.__init__)

    def push(self, screen: Screen) -> None:
        """Make `screen` the active one, on top of whatever was active before."""
        self._stack.append(screen)
        screen.on_push()
        self._notify_active_changed()

    def pop(self) -> None:
        """Deactivate the current screen and return to whatever was below it. No-op if empty.
        Notifies the screen that becomes active again via on_resume(), so it can e.g. redraw
        anything it would normally only draw once on_push()."""
        if not self._stack:
            return
        screen = self._stack.pop()
        screen.on_pop()
        if self._stack:
            self._stack[-1].on_resume()
        self._notify_active_changed()

    def replace(self, screen: Screen) -> None:
        """Atomically swaps the current top screen for `screen`, without ever
        exposing whatever is underneath -- unlike pop() immediately followed
        by push(), which synchronously (if briefly) reveals it and fires
        on_resume() on it, even though it was never meant to actually become
        visible. Used for Boot -> Logo -> Main Menu style handoffs, where each
        stage replaces the last outright rather than "returning" to anything."""
        if self._stack:
            old = self._stack.pop()
            old.on_pop()
        self._stack.append(screen)
        screen.on_push()
        self._notify_active_changed()

    def _notify_active_changed(self) -> None:
        if self._on_active_changed is not None:
            self._on_active_changed(self.active)

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
