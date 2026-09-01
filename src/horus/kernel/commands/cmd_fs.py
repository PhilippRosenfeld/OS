from sqlite3 import NotSupportedError

import pyglet

from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command
from horus.filesystem.node import NodeType, ProtectedFileError
from horus.filesystem.permissions import AccessDeniedError
from horus.filesystem.file_types import FILE_TYPES
from horus.filesystem.cipher import WrongKeyError
from horus.ui.loading_screen import LoadingScreen
import re
import secrets
import random
import logging

logger = logging.getLogger(__name__)

_PROGRESS_BAR_WIDTH = 24
_PROGRESS_STALL_CHANCE = 0.35  # chance a tick makes no progress at all -- a stutter
_PROGRESS_MIN_STEP = 3  # percentage points gained on a non-stalled tick
_PROGRESS_MAX_STEP = 12


def _render_progress_bar(ctx, row: int, percent: float) -> None:
    percent = max(0.0, min(100.0, percent))
    filled = round(_PROGRESS_BAR_WIDTH * percent / 100)
    bar = "#" * filled + "-" * (_PROGRESS_BAR_WIDTH - filled)
    ctx.screen.write_string(0, row, f"[{bar}] {percent:3.0f}%")


def _run_with_progress_bar(ctx, sound_name: str, on_complete, interval: float) -> None:
    """Shows a progress bar on the line right after the cursor's current
    position, ticking forward at random (and sometimes stalling entirely --
    a stutter, not steady progress) until it hits 100%, then calls
    on_complete(). Plays `sound_name` on loop for exactly as long as the bar
    takes, stopping the instant it completes. Total duration is therefore
    different every time, not a fixed animation length.

    Only call this once the operation is already known to succeed -- it's a
    purely cosmetic delay before revealing a result that's already decided,
    not a validation step. Pushes a LoadingScreen for the duration so the
    shell underneath doesn't print a fresh prompt or blink its cursor over
    the animation (the calling command has already returned by the time the
    ticks are still running)."""
    bar_row = ctx.screen.cursor_row
    player = ctx.sounds.play_looped(sound_name) if ctx.sounds is not None else None
    loading_screen = LoadingScreen(ctx.screen, ctx.screens) if ctx.screens is not None else None
    if loading_screen is not None:
        ctx.screens.push(loading_screen)

    state = {"percent": 0.0}
    _render_progress_bar(ctx, bar_row, 0.0)

    def _tick(dt: float) -> None:
        if random.random() < _PROGRESS_STALL_CHANCE:
            return  # stutter: this tick makes no progress

        state["percent"] += random.uniform(_PROGRESS_MIN_STEP, _PROGRESS_MAX_STEP)
        if state["percent"] >= 100:
            pyglet.clock.unschedule(_tick)
            if player is not None:
                player.pause()
            on_complete()  # writes the result at bar_row before start_line() below overwrites it
            if loading_screen is not None:
                ctx.screens.pop()
        else:
            _render_progress_bar(ctx, bar_row, state["percent"])

    pyglet.clock.schedule_interval(_tick, interval)

_FLAG_ALIASES = {
    "p": "protected", "protected": "protected",
    "h": "hidden", "hidden": "hidden",
    "i": "immutable", "immutable": "immutable",
}

# One sign followed by either one long name, or a run of one-letter shorthands.
_FLAG_GROUP = re.compile(r"([+-])(protected|hidden|immutable|[phi]+)")

def _parse_flags(flags_str: str) -> dict[str, bool]:
    """Parses strings like '+p+h-i', '+pi-h', or '+protected-hidden' into
    {'protected': True, 'hidden': True, 'immutable': False}."""
    matches = _FLAG_GROUP.findall(flags_str)
    consumed = "".join(f"{sign}{body}" for sign, body in matches)
    if consumed != flags_str:
        raise ValueError(f"invalid flag syntax: '{flags_str}'")

    updates: dict[str, bool] = {}
    for sign, body in matches:
        value = (sign == "+")
        if body in ("protected", "hidden", "immutable"):
            updates[body] = value
        else:
            for letter in body:
                updates[_FLAG_ALIASES[letter]] = value
    return updates

def _build_ls_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="ls", add_help=True, description="List current directory content")
    parser.add_argument("-a", "--all", action="store_true", help="Show all files, including directory entries and hidden files")
    parser.add_argument("-m", "--meta", action="store_true", help="Shows the metadata")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recursively displays sub-directories.")
    parser.add_argument("-R", "--tree", action="store_true", help="Show subdirectories treelike, indented")
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
    parser.add_argument("-i", "--immutable", action="store_true", help="Makes directory immutable")
    return parser

def _build_rm_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="rm", add_help=True, description="Remove a file or directory")
    parser.add_argument("path", nargs=1)
    return parser

def _build_chmod_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="chmod", add_help=True,
                                    description="Change file/directory permissions")
    parser.add_argument("mode", help="3-digit octal mode, e.g. 755")
    parser.add_argument("path")
    return parser

def _build_chattr_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="chattr", add_help=False,
                                    description="Toggle protected/hidden/immutable flags")
    return parser

def _build_cat_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="cat", add_help=True, description="Print a file's contents")
    parser.add_argument("path")
    return parser

def _build_encrypt_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="encrypt", add_help=True, description="Encrypt a file")
    parser.add_argument("path")
    parser.add_argument("-k", "--key", help="Optional encryption key")
    parser.add_argument("-m", "--method", choices=["xor", "aes"], default="xor", help="Encryption method to use (default: xor)")
    return parser

def _build_decrypt_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="decrypt", add_help=True, description="Decrypt a file")
    parser.add_argument("path")
    parser.add_argument("-k", "--key", required=True, help="Decryption key")
    parser.add_argument("-m", "--method", choices=["xor", "aes"], default="xor",
                         help="Must match the method the file was encrypted with (default: xor)")
    return parser

_ls_parser = _build_ls_parser()
_cd_parser = _build_cd_parser()
_mkdir_parser = _build_mkdir_parser()
_rm_parser = _build_rm_parser()
_chmod_parser = _build_chmod_parser()
_chattr_parser = _build_chattr_parser()
_cat_parser = _build_cat_parser()
_encrypt_parser = _build_encrypt_parser()
_decrypt_parser = _build_decrypt_parser()

def _print_node(ctx, node, show_meta: bool) -> None:
    type = "DIRECTORY" if node.type is NodeType.DIRECTORY else "FILE"
    hidden = "H" if node.hidden else "V"
    protected = "P" if node.protected else "U"
    immutable = "I" if node.immutable else "M"
    if show_meta:
        created_at = node.created_at.isoformat(sep=" ", timespec="seconds")
        modified_at = node.modified_at.isoformat(sep=" ", timespec="seconds")
        ctx.write_line(f"{node.permissions}    {hidden}-{protected}-{immutable}    {node.owner}   {type}   {node.size} bytes   C:{created_at}   M:{modified_at}   {node.name}")
    else:
        ctx.write_line(f"{node.permissions}   {node.owner}   {type}   {node.name}")

def _print_tree(ctx, fs, path: str, show_all: bool, depth: int = 0) -> None:
    """Recursively writes a directory's contents with indentation showing
    nesting depth. Called once per directory, not via list_dir(recursive=True),
    so parent/child structure is preserved for the indentation."""
    entries = fs.list_dir(path, show_all=show_all)
    entries.sort(key=lambda n: n.name)

    for entry in entries:
        indent = "  " * depth
        marker = "/" if entry.type == NodeType.DIRECTORY else ""
        ctx.write_line(f"{indent}{entry.name}{marker}")

        if entry.type == NodeType.DIRECTORY:
            child_path = path.rstrip("/") + "/" + entry.name
            _print_tree(ctx, fs, child_path, show_all, depth + 1)

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
        if args.tree:
            _print_tree(ctx, ctx.fs, ctx.cwd, show_all=args.all)
        else:
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

    path = ctx.resolve_path(args.path)

    try:
        ctx.fs.mkdir(path, user=ctx.effective_user, hidden=args.hidden, protected=args.protected, immutable=args.immutable)
    except FileExistsError:
        ctx.write_line(f"mkdir: cannot create directory '{args.path}': File exists")
    except ProtectedFileError:
        ctx.write_line(f"mkdir: cannot create directory '{args.path}': Directory is protected")
    except (FileNotFoundError, NotADirectoryError) as e:
        ctx.write_line(f"mkdir: cannot create directory '{args.path}': {e}")
    except Exception as e:
        ctx.write_line(f"mkdir: error creating directory '{args.path}': {e}")
        
        
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


@command("chmod", help_text="Change file/directory permissions")
def chmod(ctx, argv: list[str]) -> None:
    try:
        args = _chmod_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    path = ctx.resolve_path(args.path)

    try: 
        ctx.fs.chmod(path, mode=args.mode, user=ctx.effective_user)
    except ValueError as e:
        ctx.write_line(f"chmod: {e}")
    except FileNotFoundError as e:
        ctx.write_line(f"chmod: cannot access '{args.path}': No such file or directory")
    except AccessDeniedError as e:
        ctx.write_line(f"chmod: changing permissions of '{args.path}': Operation not permitted")

@command("chattr", help_text="Toggle protected/hidden/immutable flags")
def chattr(ctx, argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        ctx.write_line(_CHATTR_HELP)
        return

    if len(argv) != 2:
        ctx.write_line("usage: chattr <flags> <path>")
        return

    flags_str, raw_path = argv   # beide direkt aus argv, keine args.flags/args.path mehr

    try:
        updates = _parse_flags(flags_str)
    except ValueError as e:
        ctx.write_line(f"chattr: {e}")
        return

    if not updates:
        ctx.write_line("chattr: no flags given, e.g. +p, -hidden, +p+h-i")
        return

    path = ctx.resolve_path(raw_path)
    try:
        ctx.fs.set_attributes(path, user=ctx.effective_user, **updates)
    except FileNotFoundError:
        ctx.write_line(f"chattr: cannot access '{raw_path}': No such file or directory")
    except AccessDeniedError:
        ctx.write_line(f"chattr: changing attributes of '{raw_path}': Operation not permitted")


@command("cat", help_text="Print a file's contents")
def cat(ctx, argv: list[str]) -> None:
    try:
        args = _cat_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    path = ctx.resolve_path(args.path)
    cat_supported_types = [ext for ext, category in FILE_TYPES.items() if category == "text"]

    try:
        file_type = ctx.fs.get_file_type(path)
        if file_type == ".crypt":
            ctx.write_line(f"cat: {args.path}: File is encrypted, decrypt it first")
            return
        elif file_type in cat_supported_types:
            content = ctx.fs.read_file(path, user=ctx.effective_user)
        else:
            raise NotSupportedError(f"cat: {args.path}: Not a text file")
    except FileNotFoundError:
        if ctx.fs.exists(path):
            ctx.write_line(f"cat: {args.path}: Is a directory")
        else:
            ctx.write_line(f"cat: {args.path}: No such file or directory")
        return
    except AccessDeniedError:
        ctx.write_line(f"cat: {args.path}: Permission denied")
        return
    except NotSupportedError:
        ctx.write_line(f"cat: {args.path}: Not a text file, supported file types: {cat_supported_types}")
        return

    ctx.write_line(content)

@command("encrypt", help_text="Encrypt a file")
def encrypt(ctx, argv: list[str]) -> None:
    try:
        args = _encrypt_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    path = ctx.resolve_path(args.path)
    key = args.key or secrets.token_hex(4)

    try:
        new_path = ctx.fs.encrypt_file(path, user=ctx.effective_user, key=key, method=args.method)
    except FileNotFoundError:
        if ctx.fs.exists(path):
            ctx.write_line(f"encrypt: {args.path}: Is a directory")
        else:
            ctx.write_line(f"encrypt: {args.path}: No such file or directory")
        return
    except AccessDeniedError:
        ctx.write_line(f"encrypt: {args.path}: Permission denied")
        return
    except (ValueError, FileExistsError) as e:
        ctx.write_line(f"encrypt: {e}")
        return

    logger.info(f"encrypt: '{path}' -> '{new_path}' key='{key}' method='{args.method}'")
    ctx.write_line(f"Encrypting {args.path}...")

    def _reveal_encrypt_result() -> None:
        ctx.write_line(f"Encrypted: {args.path} -> {new_path.rsplit('/', 1)[-1]} (method={args.method})")
        if not args.key:
            ctx.write_line(f"Generated key: {key} -- remember it, you'll need it to decrypt")
            

    _run_with_progress_bar(ctx, "crypt", _reveal_encrypt_result, 0.15)


@command("decrypt", help_text="Decrypt a file")
def decrypt(ctx, argv: list[str]) -> None:
    try:
        args = _decrypt_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    path = ctx.resolve_path(args.path)

    try:
        new_path = ctx.fs.decrypt_file(path, user=ctx.effective_user, key=args.key, method=args.method)
    except FileNotFoundError:
        if ctx.fs.exists(path):
            ctx.write_line(f"decrypt: {args.path}: Is a directory")
        else:
            ctx.write_line(f"decrypt: {args.path}: No such file or directory")
        return
    except AccessDeniedError:
        ctx.write_line(f"decrypt: {args.path}: Permission denied")
        return
    except WrongKeyError:
        ctx.write_line(f"decrypt: {args.path}: wrong key or method")
        return
    except (ValueError, FileExistsError) as e:
        ctx.write_line(f"decrypt: {e}")
        return

    logger.info(f"decrypt: '{path}' -> '{new_path}' key='{args.key}' method='{args.method}'")
    ctx.write_line(f"Decrypting {args.path}...")

    def _reveal_decrypt_result() -> None:
        ctx.write_line(f"Decrypted: {args.path} -> {new_path.rsplit('/', 1)[-1]}")

    _run_with_progress_bar(ctx, "crypt", _reveal_decrypt_result, 0.5)
