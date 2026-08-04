from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command

def _build_ls_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="ls", add_help=True)
    parser.add_argument("-a", "--all", default=None, help="Show all files, including directory entries and hidden files")
    parser.add_argument("-m", "--meta", default=None, help="Shows the metadata")
    parser.add_argument("-r", "--recursive", default=None, help="Recursively displays sub-directories.")
    return parser

_ls_parser = _build_ls_parser()

@command("ls", help_text="List current directory content")
def ls(ctx, argv: list[str]) -> None:
    try:
        args = _color_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

        