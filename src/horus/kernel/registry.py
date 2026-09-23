from typing import Callable

from horus.session.context import Context

CommandHandler = Callable[[Context, list[str]], None]

class Registry:
    """Central register for all commands. Commands register themselves 
    here and the kernel looks them up at dispatch time."""

    def __init__(self) -> None:
        self._commands: dict[str, CommandHandler] = {}
        self._help: dict[str, str] = {}
        self._category: dict[str, str | None] = {}

    def register(self, name: str, handler: CommandHandler, help_text: str = "", category: str | None = None) -> None:
        """Register a command in the registry. `category` (e.g. "filesystem",
        "system", "user") is optional metadata used to group commands in
        `man`'s -f/-s/-u listings -- a command with no category just never
        matches any of those filters, but still shows up in the full,
        unfiltered listing."""
        if not name or handler is None:
            raise ValueError("command name and handler must be provided.")
        if name in self._commands:
            raise ValueError(f"command '{name}' is already registered.")

        self._commands[name] = handler
        self._help[name] = help_text
        self._category[name] = category

    def lookup(self, name: str) -> CommandHandler | None:
        """Lookup a given command and return its handler."""
        if name is None:
            return None
        return self._commands.get(name)

    def unregister(self, name: str) -> CommandHandler | None:
        """Unregisters a given command. Returns unregistered command if successful, None otherwise."""
        if name is None:
            return None
        self._help.pop(name, None)
        self._category.pop(name, None)
        return self._commands.pop(name, None)

    def names(self) -> list[str]:
        """Gets all registered commands."""
        return list(self._commands.keys())

    def help_text(self, name) -> str:
        """Gets the help text for the registered command."""
        if name is None:
            return ""
        return self._help.get(name, "")

    def category(self, name) -> str | None:
        """Gets the category the command was registered under, or None if
        it wasn't given one."""
        if name is None:
            return None
        return self._category.get(name)



registry = Registry()


def command(name: str, help_text: str = "", category: str | None = None) -> Callable[[CommandHandler], CommandHandler]:
    """Decorator: registers the decorated function under `name` in the
    module-level registry.

        @command("echo", help_text="print the given text")
        def echo(ctx, argv): ...
    """
    def decorator(func: CommandHandler) -> CommandHandler:
        registry.register(name, func, help_text, category=category)
        return func
    return decorator