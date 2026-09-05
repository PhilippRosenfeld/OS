from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command
from horus.processes.process_view import DEFAULT_SORT, SORT_KEYS, format_system_summary, format_uptime, sort_processes
from horus.ui.top_screen import TopScreen


def _render_top(ctx, sort_by: str | None = None) -> None:
    """One-shot fallback for when there's no screen stack to take over (e.g.
    a minimal test Context) -- prints a single snapshot via ctx.write_line
    instead of the live, refreshing view. `sort_by` is optional: leaving it
    unset keeps the process table's own (insertion) order, e.g. for ps."""
    processes = ctx.process_table.list_processes()
    if sort_by is not None:
        processes = sort_processes(processes, sort_by)
    ctx.write_line(format_system_summary(ctx.process_table))
    ctx.write_line(f"{'PID':<8}{'USER':<12}{'CPU(MHz)':<10}{'MEM(KB)':<12}{'UPTIME':<10}{'NAME'}")
    ctx.write_line("-" * 70)
    for proc in processes:
        uptime = format_uptime(proc.started_at)
        ctx.write_line(f"{proc.pid:<8}{proc.owner:<12}{proc.cpu_mhz:<10.1f}{proc.mem_kb:<12}{uptime:<10}{proc.name}")

def _build_top_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="top", add_help=True, description="Display system processes")
    parser.add_argument("-s", "--sort", choices=sorted(SORT_KEYS), default=DEFAULT_SORT,
                         help=f"Sort processes by this column (default: {DEFAULT_SORT})")
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
        args = _top_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    if ctx.screens is None:
        _render_top(ctx, sort_by=args.sort)
        return

    ctx.screens.push(TopScreen(ctx.screen, ctx.process_table, ctx.screens, sort_by=args.sort))
    
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

    if not ctx.process_table.can_kill(args.pid, user=ctx.effective_user, role=ctx.effective_role):
        if ctx.sounds is not None:
            ctx.sounds.play("error_notification")
        ctx.write_line(f"kill: ({args.pid}) - Operation not permitted")
        return

    if proc.critical:
        ctx.write_line(f"WARNING: '{proc.name}' (PID {proc.pid}) is a critical system process.")
        ctx.write_line("Killing it will crash the system. Continue? (y/n)")

        def _on_confirm(answer: str) -> None:
            if answer.strip().lower() in ("y", "yes"):
                _finish_kill(ctx, proc)
            else:
                ctx.write_line("kill: aborted")

        ctx.request_input(_on_confirm)
        return

    _finish_kill(ctx, proc)


def _finish_kill(ctx, proc) -> None:
    """Actually removes the process and reports the outcome. Permission was
    already checked in kill() before any confirmation prompt, so this only
    fails if the process disappeared in the meantime (e.g. it finished
    naturally between the prompt and the answer).

    Killing a critical process (e.g. init) crashes the system -- but that
    reaction lives in processes.system_reactions, subscribed to
    ProcessKilledEvent, not here: it fires the same way no matter what kills
    a critical process, not just this command. remove_process() publishes
    that event (synchronously, so the crash screen is already showing by the
    time it returns) -- this just has to stay quiet afterwards instead of
    printing over whatever the crash reaction just drew."""
    was_critical = proc.critical
    if not ctx.process_table.remove_process(proc.pid, user=ctx.effective_user, role=ctx.effective_role):
        ctx.write_line(f"kill: ({proc.pid}) - No such process")
        return

    if was_critical:
        return

    if ctx.sounds is not None:
        ctx.sounds.play("process_kill_buzz")
        ctx.sounds.set_sound_volume("process_kill_bang", 0.5)
        ctx.sounds.play("process_kill_bang")
    ctx.write_line(f"Killed process {proc.pid} ({proc.name})")