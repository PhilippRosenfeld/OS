from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command
from horus.ui.top_screen import TopScreen


def _render_top(ctx) -> None:
    """One-shot fallback for when there's no screen stack to take over (e.g.
    a minimal test Context) -- prints a single snapshot via ctx.write_line
    instead of the live, refreshing view."""
    processes = ctx.process_table.list_processes()
    ctx.write_line(f"{'PID':<8}{'USER':<12}{'CPU%':<8}{'MEM(KB)':<12}{'NAME'}")
    ctx.write_line("-" * 60)
    for proc in processes:
        ctx.write_line(f"{proc.pid:<8}{proc.owner:<12}{proc.cpu_percent:<8.2f}{proc.mem_kb:<12}{proc.name}")

def _build_top_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="top", add_help=True, description="Display system processes")
    return parser

def _build_ps_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="ps", add_help=True, description="Display system processes snapshot")
    return parser

def _build_kill_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="kill", add_help=True, description="Kill a process")
    parser.add_argument("pid", type=int, help="PID of the process to kill")
    return parser

_top_parser = _build_top_parser()
_ps_parser = _build_ps_parser()
_kill_parser = _build_kill_parser()

@command("top", help_text="Display system processes, live, until Ctrl+C")
def top(ctx, argv: list[str]) -> None:
    try:
        _top_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    if ctx.screens is None:
        _render_top(ctx)
        return

    ctx.screens.push(TopScreen(ctx.screen, ctx.process_table, ctx.screens))
    
@command("ps", help_text="Display system processes snapshot")
def ps(ctx, argv: list[str]) -> None:
    try:
        _ps_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    _render_top(ctx)
    
@command("kill", help_text="Kill a process by PID")
def kill(ctx, argv: list[str]) -> None:
    try:
        args = _kill_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    proc = ctx.process_table.get_process(args.pid)
    if proc is None:
        ctx.write_line(f"kill: ({args.pid}) - No such process")
        return

    if ctx.process_table.remove_process(args.pid, user=ctx.effective_user, role=ctx.effective_role):
        ctx.sounds.play("process_kill_buzz")
        ctx.sounds.set_sound_volume("process_kill_bang", 0.5)
        ctx.sounds.play("process_kill_bang")
        ctx.write_line(f"Killed process {args.pid} ({proc.name})")
    else:
        ctx.sounds.play("error_notification")
        ctx.write_line(f"kill: ({args.pid}) - Operation not permitted")
        