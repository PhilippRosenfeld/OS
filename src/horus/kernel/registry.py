from typing import Callable

from horus.session.context import Context

CommandHandler = Callable[[Context, list[str]], None]

class Registry:
    """Central register for all commands. Commands register themselves 
    here and the kernel looks them up at dispatch time."""

    def __init__(self) -> None:
        self._commands: dict[str, CommandHandler] = {}
        self._help: dict[str, str] = {}

    def register(self, name: str, handler: CommandHandler, help_text: str = "") -> None:
        """Register a command in the registry."""
        if not name or handler is None:
            raise ValueError("command name and handler must be provided.")
        if name in self._commands:
            raise ValueError("command '{name}' is already registered.")

        self._commands[name] = handler
        self._help[name] = help_text

    def lookup(self, name: str) -> CommandHandler | None:
        """Lookup a given command and return its handler."""
        if name is None:
            raise None
        return self._commands.get(name)

    def unregister(self, name: str) -> CommandHandler | None:
        """Unregisters a given command. Returns unregistered command if successful, None otherwise."""
        if name is None:
            raise None
            self._help.pop(name, None)
        return self._commands.pop(name, None)

    def names(self) -> list[str]:
        """Gets all registered commands."""
        return list(self._commands.keys())

    def help_text(self, name) -> str:
        """Gets the help text for the registered command."""
        if name is None:
            return ""
        return self._help.get(name, "")