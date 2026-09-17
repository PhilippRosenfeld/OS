from horus.hardware.spec import HardwareSpec
from horus.kernel.registry import command
from horus.processes.process_view import format_system_summary
from horus.ui.screens.hardware_screen import HardwareScreen, HardwareTile


def _build_hardware_screen(ctx) -> HardwareScreen:
    """Assembles the hardware overview from live data: HardwareSpec for the
    machine's static specs, ProcessTable for how much of its CPU/RAM budget
    is currently in use. Storage doesn't have a real activity signal yet
    (no I/O simulation exists), so that tile stays a placeholder.

    CPU/RAM load (and, downstream, PSU draw) can change every tick, so
    those tiles -- and the Overview summary at the top -- are kept current
    the same way TopScreen keeps `top` live: refresh() below re-derives
    their `.lines` from `table`/`hardware` on every HardwareScreen tick,
    not just once at push time."""
    hardware = ctx.hardware if ctx.hardware is not None else HardwareSpec()
    table = ctx.process_table

    overview = HardwareTile("Overview")
    cpu = HardwareTile("CPU")
    ram = HardwareTile("RAM")
    storage = HardwareTile("Storage", ["No drives detected."])
    external = HardwareTile("External")
    power = HardwareTile("Power")
    cooling = HardwareTile("Cooling")
    network = HardwareTile("Network")

    def refresh() -> None:
        overview.lines = [format_system_summary(table)]

        used_cpu = table.used_cpu_mhz()
        total_cpu = table.total_cpu_mhz
        cpu_percent = (used_cpu / total_cpu * 100) if total_cpu else 0.0
        cpu.lines = [
            hardware.cpu_name,
            f"{hardware.cpu_cores} core(s) @ {hardware.cpu_mhz} MHz",
            f"Load: {used_cpu:.0f}/{total_cpu} MHz ({cpu_percent:.1f}%)",
        ]

        used_mem = table.used_mem_kb()
        total_mem = table.total_memory_kb
        mem_percent = (used_mem / total_mem * 100) if total_mem else 0.0
        ram.lines = [
            f"{hardware.memory_count} x {hardware.memory_kb}",
            f"Total: {total_mem} KB",
            f"Used: {used_mem} KB ({mem_percent:.1f}%)",
        ]

        psu_unit = hardware.power_supply_unit
        power.lines = [
            psu_unit.name,
            f"Output: {psu_unit.power_output_watts} W",
            f"Draw: {hardware.calculate_total_power_usage():.0f} W",
        ]

        cooling_system = hardware.motherboard.cooling_system
        cooling.lines = [
            cooling_system.name,
            f"{cooling_system.coolant_type.value}: {cooling_system.coolant_amount}%",
            f"Draw: {cooling_system.calc_current_power_usage():.0f} W",
        ]

        interfaces = hardware.motherboard.network_interfaces
        network.lines = [f"{iface.name}: {iface.ip_address}" for iface in interfaces] or ["No network interfaces."]

    refresh()  # populate before the first render

    return HardwareScreen(ctx.screen, "System Overview", overview, cpu, ram, storage,
                           external, power, cooling, network, ctx.screens, refresh=refresh)


@command("sys", help_text="Show a hardware overview")
def sys(ctx, argv: list[str]) -> None:
    ctx.screens.push(_build_hardware_screen(ctx))
