from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command
from horus.filesystem.node import NodeType, ProtectedFileError

def _build_ls_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="ls", add_help=True, description="List current directory content")
    parser.add_argument("-a", "--all", action="store_true", help="Show all files, including directory entries and hidden files")
    parser.add_argument("-m", "--meta", action="store_true", help="Shows the metadata")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recursively displays sub-directories.")
    return parser

def _build_cd_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="cd", add_help=True, description="Change current directory")
    parser.add_argument("path", nargs="*") 
    return parser

def _build_mkdir_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="mkdir", add_help=True, description="Create a new directory")
    parser.add_argument("path")
    parser.add_argument("-p", "--protected", action="store_true", help="Makes directory protected")
    parser.add_argument("-H", "--hidden", action="store_true", help="Makes directory hidden")
    return parser

def _build_rm_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="rm", add_help=True, description="Remove a file or directory")
    parser.add_argument("path", nargs=1)
    return parser

_ls_parser = _build_ls_parser()
_cd_parser = _build_cd_parser()
_mkdir_parser = _build_mkdir_parser()
_rm_parser = _build_rm_parser()

def _print_node(ctx, node, show_meta: bool) -> None:
    type = "DIRECTORY" if node.type is NodeType.DIRECTORY else "FILE"
    hidden = "H" if node.hidden else "V"
    protected = "P" if node.protected else "U"
    if show_meta:
        created_at = node.created_at.isoformat(sep=" ", timespec="seconds")
        modified_at = node.modified_at.isoformat(sep=" ", timespec="seconds")
        ctx.write_line(f"{node.permissions}    {hidden}-{protected}    {node.owner}   {type}   {node.size} bytes   C:{created_at}   M:{modified_at}   {node.name}")
    else:
        ctx.write_line(f"{node.permissions}   {node.owner}   {type}   {node.name}")


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

@command("cd", help_text="Change current directory")
def cd(ctx, argv: list[str]) -> None:
    try:
        args = _cd_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    if ctx.fs.exists(ctx.resolve_path("/".join(args.path))):  # Check if the path exists
        ctx.cwd = ctx.resolve_path("/".join(args.path)) if args.path else ctx.cwd
    else:
        ctx.write_line(f"cd: No such file or directory: {'/'.join(args.path)}")
        
        
@command("mkdir", help_text="Create a new directory")
def mkdir(ctx, argv: list[str]) -> None:
    try:
        args = _mkdir_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    path = ctx.resolve_path(argv[0])

    try:
        ctx.fs.mkdir(path, hidden=args.hidden, protected=args.protected)
    except FileExistsError:
        ctx.write_line(f"mkdir: cannot create directory '{argv[0]}': File exists")
    except ProtectedFileError:
        ctx.write_line(f"mkdir: cannot create directory '{argv[0]}': Directory is protected")
    except (FileNotFoundError, NotADirectoryError) as e:
        ctx.write_line(f"mkdir: cannot create directory '{args.path}': {e}")
    except Exception as e:
        ctx.write_line(f"mkdir: error creating directory '{argv[0]}': {e}")
        
        
@command("rm", help_text="Remove a file or directory")
def rm(ctx, argv: list[str]) -> None:
    try:
        args = _rm_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    path = ctx.resolve_path(args.path[0])
    
    try:
        ctx.fs.remove(path, user=ctx.effective_user)
        ctx.write_line(f"Removed: {args.path[0]}")
    except FileNotFoundError:
        ctx.write_line(f"rm: cannot remove '{args.path[0]}': No such file or directory")
    except ProtectedFileError:
        ctx.write_line(f"rm: cannot remove '{args.path[0]}': File is protected")