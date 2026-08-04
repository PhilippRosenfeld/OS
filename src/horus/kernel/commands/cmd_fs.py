from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command
from horus.filesystem.node import NodeType

def _build_ls_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="ls", add_help=True)
    parser.add_argument("-a", "--all", action="store_true", help="Show all files, including directory entries and hidden files")
    parser.add_argument("-m", "--meta", action="store_true", help="Shows the metadata")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recursively displays sub-directories.")
    return parser

_ls_parser = _build_ls_parser()


def _print_node(ctx, node, show_meta: bool) -> None:
    if show_meta:
        ctx.write_line(f"{node.permissions}   {node.owner}   {node.type}   {node.size} bytes   {node.created_at}   {node.modified_at}   {node.name}")
    else:
        ctx.write_line(f"{node.permissions}   {node.owner}   {node.type}   {node.name}")


def _list_directory(ctx, path: str, args) -> None:
    """Lists one directory's contents, then (if args.recursive) descends into each
    subdirectory in turn, printing a 'path:' header before each one."""
    nodes = ctx.fs.list_dir(path=path, show_all=args.all)
    if args.recursive:
        ctx.write_line(f"{path}:")
    for node in nodes:
        _print_node(ctx, node, args.meta)
    if args.recursive:
        for node in nodes:
            if node.type == NodeType.DIRECTORY:
                ctx.write_line("")
                _list_directory(ctx, path.rstrip("/") + "/" + node.name, args)


@command("ls", help_text="List current directory content")
def ls(ctx, argv: list[str]) -> None:
    try:
        args = _ls_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return
    try:
        _list_directory(ctx, ctx.cwd, args)
    except FileNotFoundError as e:
        ctx.write_line(f"ls: File not found: {e}")
        return
    except NotADirectoryError as e:
        ctx.write_line(f"ls: Path does not lead to a directory: {e}")
        return
