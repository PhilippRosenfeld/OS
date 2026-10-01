from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command
from horus.processes.memory import process_memory
from horus.processes.process import process as Process
from horus.session.user import UserRole

_DUMP_WIDTH = 16  # bytes per memdump line


def _build_free_parser() -> CommandArgumentParser:
    return CommandArgumentParser(prog="free", add_help=True, description="Show RAM and swap usage")


def _build_memdump_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="memdump", add_help=True, description="Hex dump of a process's memory")
    parser.add_argument("pid", type=int, help="PID of the process")
    parser.add_argument("-o", "--offset", type=lambda v: int(v, 0), default=0,
                        help="Start address within the process's memory (e.g. 0x400, default 0)")
    parser.add_argument("-n", "--lines", type=int, default=16, help=f"Lines of {_DUMP_WIDTH} bytes to show (default 16)")
    return parser


def _build_stress_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="stress", add_help=True,
                                    description="Start a process that loads the CPU and/or memory")
    parser.add_argument("-c", "--cpu", type=float, default=0.0, help="CPU load in MHz (default 0)")
    parser.add_argument("-m", "--mem", type=int, default=4096, help="Memory in KB (default 4096)")
    parser.add_argument("--name", default="stress", help="Process name (default 'stress')")
    return parser


_free_parser = _build_free_parser()
_memdump_parser = _build_memdump_parser()
_stress_parser = _build_stress_parser()


def _parse(parser, ctx, argv):
    try:
        return parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return None


@command("free", help_text="Show RAM and swap usage", category="system")
def free(ctx, argv: list[str]) -> None:
    if _parse(_free_parser, ctx, argv) is None:
        return
    memory = ctx.memory_manager
    table = ctx.process_table
    if memory is not None:
        total, used, swap_total, swap_used = memory.total_kb, memory.used_kb, memory.swap_kb, memory.swap_used_kb
    else:  # no MemoryManager running: everything a process asks for counts as resident
        total, used, swap_total, swap_used = table.total_memory_kb, table.used_mem_kb(), 0, 0
    ctx.write_line(f"{'':<7}{'total':>10}{'used':>10}{'free':>10}   (KB)")
    ctx.write_line(f"{'Mem:':<7}{total:>10}{used:>10}{max(0, total - used):>10}")
    ctx.write_line(f"{'Swap:':<7}{swap_total:>10}{swap_used:>10}{max(0, swap_total - swap_used):>10}")


@command("memdump", help_text="Hex dump of a process's memory", category="system")
def memdump(ctx, argv: list[str]) -> None:
    args = _parse(_memdump_parser, ctx, argv)
    if args is None:
        return
    proc = ctx.process_table.get_process(args.pid)
    if proc is None:
        ctx.write_line(f"memdump: ({args.pid}) - No such process")
        return
    if proc.owner != ctx.effective_user and ctx.effective_role < UserRole.ADMIN:
        ctx.write_line(f"memdump: ({args.pid}) - Operation not permitted")
        return

    size = proc.mem_kb * 1024
    offset = max(0, args.offset)
    if offset >= size:
        ctx.write_line(f"memdump: offset 0x{offset:X} is past the end of '{proc.name}' ({size} bytes)")
        return
    data = process_memory(proc, offset, max(1, args.lines) * _DUMP_WIDTH)
    swapped = f", {proc.swapped_kb} KB swapped out" if proc.swapped_kb else ""
    ctx.write_line(f"{proc.name} (PID {proc.pid}) -- {proc.mem_kb} KB{swapped}")
    for i in range(0, len(data), _DUMP_WIDTH):
        chunk = data[i:i + _DUMP_WIDTH]
        hex_part = " ".join(f"{b:02X}" for b in chunk).ljust(_DUMP_WIDTH * 3 - 1)
        text_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        ctx.write_line(f"{offset + i:08X}  {hex_part}  |{text_part}|")


@command("stress", help_text="Start a process that loads the CPU and/or memory", category="system")
def stress(ctx, argv: list[str]) -> None:
    args = _parse(_stress_parser, ctx, argv)
    if args is None:
        return
    if args.cpu < 0 or args.mem < 0:
        ctx.write_line("stress: --cpu and --mem must not be negative")
        return
    proc = ctx.process_table.add_process(Process(name=args.name, pid=0, owner=ctx.effective_user,
                                                 cpu_mhz=args.cpu, mem_kb=args.mem, volatility=0.5))
    ctx.write_line(f"Started '{proc.name}' (PID {proc.pid}): {args.cpu:.0f} MHz, {args.mem} KB -- stop it with 'kill {proc.pid}'")
