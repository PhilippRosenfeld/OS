from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command

def _build_echo_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="echo", add_help=True)
    parser.add_argument("text", nargs="*")
    return parser

def _build_whoami_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="whoami", add_help=True)
    return parser

_echo_parser = _build_echo_parser()
_whoami_parser = _build_whoami_parser()


@command("echo", help_text="Echoes the input text")
def echo(ctx, argv: list[str]) -> None:
    try:
        args = _echo_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    ctx.write_line(" ".join(args.text))

@command("whoami", help_text="Who are you?")
def whoami(ctx, argv: list[str]) -> None:
    ctx.write_line("" + ctx.user)
    
