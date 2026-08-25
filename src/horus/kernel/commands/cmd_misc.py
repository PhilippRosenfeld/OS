from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command
from horus.display.colors import NAMED_COLORS
from horus.session.auth import verify_password


def _build_color_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="color", add_help=True, description="Set terminal colors")
    parser.add_argument("-f", "--fg", default=None, help="Foreground color")
    parser.add_argument("-b", "--bg", default=None, help="Background color")
    parser.add_argument("-o", "--omnia", action="store_true", help="Changes the colors retroactively")
    return parser

def _build_su_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="su", add_help=True, description="Change yourself")
    parser.add_argument("username", nargs="?", default= "root", help="User to switch to")
    return parser

_color_parser = _build_color_parser()
_su_parser = _build_su_parser()

@command("color", help_text="Set terminal colors")
def color(ctx, argv: list[str]) -> None:
    try:
        args = _color_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return
    
    fg = NAMED_COLORS.get(args.fg) if args.fg else None
    bg = NAMED_COLORS.get(args.bg) if args.bg else None

    if args.fg and fg is None:
        ctx.write_line(f"Color: unknown color: '{args.fg}'")
        return
    
    if args.bg and bg is None:
        ctx.write_line(f"Color: unknown color: '{args.bg}'")
        return

    if fg is None and bg is None:
        return

    ctx.screen.set_default_color(fg, bg)

    if args.omnia:
        ctx.screen.recolor_all(fg, bg)

@command("su", help_text="Change yourself")
def su(ctx, argv: list[str]) -> None:
    try:
        args = _su_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    target = ctx.users.get(args.username)
    if target is None:
        ctx.write_line(f"su: user '{args.username}' does not exist")
        return

    # root can switch to anyone without a password, and a user without a
    # password set (target.password_hash is None) needs none either
    if ctx.effective_user == "root" or target.password_hash is None:
        ctx.user = args.username
        ctx.effective_user = args.username
        ctx.write_line(f"switched to user '{args.username}'")
        return

    def _check_password(entered: str) -> None:
        if verify_password(entered, target.password_hash):
            ctx.user = args.username
            ctx.effective_user = args.username
            ctx.write_line(f"switched to user '{args.username}'")
        else:
            ctx.write_line("su: authentication failure")

    ctx.write_line("Password:")
    ctx.request_input(_check_password, masked=True)
