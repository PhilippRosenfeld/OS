from horus.apps.netman.screen import NetmanWindow
from horus.apps.window_manager import show_app
from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command


def _build_netman_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="netman", add_help=True, description="Start network manager")
    return parser

_netman_parser = _build_netman_parser()

@command("netman", help_text="Start network manager", category="user")
def netman(ctx, argv: list[str]) -> None:
    try:
        _netman_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    # brings back a netman still running in the background, or starts one
    show_app(ctx, "netman", lambda: NetmanWindow(ctx))
