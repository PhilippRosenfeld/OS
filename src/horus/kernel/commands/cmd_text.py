from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command, registry


def _build_echo_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="echo", add_help=True, description="Echoes the input text")
    parser.add_argument("text", nargs="*")
    return parser

def _build_whoami_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="whoami", add_help=True, description="Who are you?")
    return parser

def _build_man_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="man", add_help=True, description="Displays manual listing available commands")
    parser.add_argument("command", nargs="?", default=None, help="Command to display manual for")
    parser.add_argument("-f", "--filesystem", action="store_true", help="Display all commands related to the filesystem")
    parser.add_argument("-s", "--system", action="store_true", help="Display all commands related to the system")
    parser.add_argument("-u", "--user", action="store_true", help="Display all commands related to the user")
    return parser

def _build_cls_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="cls", add_help=True, description="Clears the screen")
    return parser

_echo_parser = _build_echo_parser()
_whoami_parser = _build_whoami_parser()
_man_parser = _build_man_parser()
_cls_parser = _build_cls_parser()


@command("echo", help_text="Echoes the input text")
def echo(ctx, argv: list[str]) -> None:
    try:
        args = _echo_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    ctx.write_line(" ".join(args.text))

@command("whoami", help_text="Who are you?", category="user")
def whoami(ctx, argv: list[str]) -> None:
    try:
        _whoami_parser.parse_args(argv)  # only used for its --help/error side effect
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    ctx.write_line("" + ctx.user)

@command("man", help_text="Displays manual listing available commands")
def man(ctx, argv: list[str]) -> None:
    try:
        args = _man_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    if args.command:
        # A specific command's manual takes priority over -f/-s/-u -- asking
        # for both at once doesn't really make sense, so this just ignores
        # the category flags rather than erroring out over it.
        handler = registry.lookup(args.command)
        if handler is None:
            ctx.write_line(f"man: no manual entry for '{args.command}'")
            return
        # Every command's own parser already builds a full usage/description
        # page for --help (see CommandArgumentParser.exit()) -- reusing it
        # here means this can never drift out of sync with the command's
        # actual arguments, unlike a separate, hand-maintained manual would.
        handler(ctx, ["--help"])
        return

    categories = [category for category, flag in
                  (("filesystem", args.filesystem), ("system", args.system), ("user", args.user)) if flag]
    names = sorted(registry.names())
    if categories:
        names = [name for name in names if registry.category(name) in categories]

    for name in names:
        ctx.write_line(f"{name}: {registry.help_text(name)}")

@command("cls", help_text="Clears the screen")
def cls(ctx, argv: list[str]) -> None:
    try:
        _cls_parser.parse_args(argv)  # only used for its --help/error side effect
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return
    ctx.screen.clear()
    ctx.screen.cursor_row = 0
