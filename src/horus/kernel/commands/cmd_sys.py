from horus.hardware.spec import HardwareSpec
from horus.kernel.registry import command
from horus.processes.process_view import format_system_summary
from horus.ui.screens.hardware_screen import HardwareScreen, HardwareTile


def _build_hardware_screen(ctx) -> HardwareScreen:
    """Assembles the hardware overview from live data: HardwareSpec for the
    machine's static specs, ProcessTable for how much of its CPU/RAM budget
    is currently in use. Storage and external devices aren't modeled
    anywhere yet, so their tiles are placeholders until that exists."""
    hardware = ctx.hardware if ctx.hardware is not None else HardwareSpec()
    table = ctx.process_table

    overview = HardwareTile("Overview", [format_system_summary(table)])

    used_cpu = table.used_cpu_mhz()
    total_cpu = table.total_cpu_mhz
    cpu_percent = (used_cpu / total_cpu * 100) if total_cpu else 0.0
    cpu = HardwareTile("CPU", [
        hardware.cpu_name,
        f"{hardware.cpu_cores} core(s) @ {hardware.cpu_mhz} MHz",
        f"Load: {used_cpu:.0f}/{total_cpu} MHz ({cpu_percent:.1f}%)",
    ])

    used_mem = table.used_mem_kb()
    total_mem = table.total_memory_kb
    mem_percent = (used_mem / total_mem * 100) if total_mem else 0.0
    ram = HardwareTile("RAM", [
        f"{hardware.memory_count} x {hardware.memory_kb}",
        f"Total: {total_mem} KB",
        f"Used: {used_mem} KB ({mem_percent:.1f}%)",
    ])

    storage = HardwareTile("Storage", ["No drives detected."])
    external = HardwareTile("External", ["No external devices connected."])

    return HardwareScreen(ctx.screen, "System Overview", overview, cpu, ram, storage, external, ctx.screens)


@command("sys", help_text="Show a hardware overview")
def sys(ctx, argv: list[str]) -> None:
    ctx.screens.push(_build_hardware_screen(ctx))
