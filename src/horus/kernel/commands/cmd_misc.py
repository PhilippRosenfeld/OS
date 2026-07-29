from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command
from horus.display.colors import NAMED_COLORS


def _build_color_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="color", add_help=True)
    parser.add_argument("-f", "--fg", default=None, help="Foreground color")
    parser.add_argument("-b", "--bg", default=None, help="Background color")
    parser.add_argument("-o", "--omnia", action="store_true", help="Changes the colors retroactively")
    return parser

_color_parser = _build_color_parser()

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

