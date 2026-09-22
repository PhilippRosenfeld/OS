from horus.hardware.spec import HardwareSpec
from horus.kernel.commands.command_parser import CommandArgumentParser, CommandParseError
from horus.kernel.registry import command
from horus.processes.process_view import format_system_summary
from horus.ui.screens.detail_screen import DetailScreen, StatusBarInfo
from horus.ui.screens.hardware_screen import HardwareScreen, HardwareTile
from horus.ui.screens.settings_screen import SettingOption

# One (mutually exclusive) flag per hardware tile, so e.g. 'sys -c' jumps
# straight to the Cooling detail screen instead of opening the overview and
# navigating to it by hand. Letters chosen to avoid clashing with each other
# case-sensitively (-C is CPU, -c is Cooling).
_TILE_FLAGS = {
    "cpu": ("-C", "--cpu"),
    "ram": ("-r", "--ram"),
    "storage": ("-s", "--storage"),
    "power": ("-p", "--power"),
    "cooling": ("-c", "--cooling"),
    "network": ("-n", "--network"),
}


def _build_sys_parser() -> CommandArgumentParser:
    parser = CommandArgumentParser(prog="sys", add_help=True,
                                    description="Show a hardware overview, or jump straight to one component's detail screen")
    group = parser.add_mutually_exclusive_group()
    for name, (short, long) in _TILE_FLAGS.items():
        group.add_argument(short, long, dest=name, action="store_true", help=f"Open the {name.capitalize()} detail screen directly")
    return parser


_sys_parser = _build_sys_parser()


def _cpu_detail_lines(hardware, table) -> list[str]:
    cpus = hardware.installed_cpus()
    used_cpu = table.used_cpu_mhz()
    total_cpu = table.total_cpu_mhz
    cpu_percent = (used_cpu / total_cpu * 100) if total_cpu else 0.0
    lines = [
        hardware.cpu_name,
        f"Manufacturer: {cpus[0].manufacturer}" if cpus else "Manufacturer: -",
        f"Cores: {hardware.cpu_cores}",
        f"Clock: {hardware.cpu_mhz} MHz",
        f"Power range: {cpus[0].power_usage_watts_min}-{cpus[0].power_usage_watts_max} W" if cpus else "Power range: -",
        "",
        f"Load: {used_cpu:.0f}/{total_cpu} MHz ({cpu_percent:.1f}%)",
        f"Current draw: {sum(cpu.calc_current_power_usage() for cpu in cpus):.0f} W",
    ]
    return lines


def _ram_detail_lines(hardware, table) -> list[str]:
    ram_sticks = hardware.installed_ram()
    used_mem = table.used_mem_kb()
    total_mem = table.total_memory_kb
    mem_percent = (used_mem / total_mem * 100) if total_mem else 0.0
    lines = [
        f"{hardware.memory_count} x {hardware.memory_kb}",
        f"Manufacturer: {ram_sticks[0].manufacturer}" if ram_sticks else "Manufacturer: -",
        f"Power range per stick: {ram_sticks[0].power_usage_watts_min}-{ram_sticks[0].power_usage_watts_max} W" if ram_sticks else "Power range: -",
        "",
        f"Total: {total_mem} KB",
        f"Used: {used_mem} KB ({mem_percent:.1f}%)",
        f"Current draw: {sum(ram.calc_current_power_usage() for ram in ram_sticks):.0f} W",
    ]
    return lines


def _storage_detail_lines(hardware) -> list[str]:
    drives = hardware.installed_storage()
    if not drives:
        return ["No drives detected."]
    lines = []
    for drive in drives:
        if lines:
            lines.append("")
        lines.extend([
            drive.name,
            f"Manufacturer: {drive.manufacturer}",
            f"Size: {drive.size} KB",
            f"Power: {drive.power_usage_watts} W",
        ])
    return lines


def _power_detail_lines(hardware) -> list[str]:
    psu_unit = hardware.power_supply_unit
    total_draw = hardware.calculate_total_power_usage()
    over_budget = total_draw > psu_unit.power_output_watts
    lines = [
        psu_unit.name,
        f"Manufacturer: {psu_unit.manufacturer}",
        f"Rated output: {psu_unit.power_output_watts} W",
        "",
        f"Current total draw: {total_draw:.0f} W",
        f"Headroom: {psu_unit.power_output_watts - total_draw:.0f} W",
        f"Status: {'OVER BUDGET' if over_budget else 'OK'}",
    ]
    return lines


def _cooling_status(hardware) -> StatusBarInfo:
    """Deactivated never lights up (nothing to warn about), a warning-level
    temperature blinks to draw attention, and critical/OK stay lit steady."""
    cooling_system = hardware.motherboard.cooling_system
    if not cooling_system.active:
        return StatusBarInfo("Status: INACTIVE", lit=False)
    if hardware.temperature_celsius >= hardware.critical_temperature:
        return StatusBarInfo("Status: CRITICAL")
    if hardware.temperature_celsius >= hardware.warning_temperature:
        return StatusBarInfo("Status: WARNING", blink=True)
    return StatusBarInfo("Status: OK")


def _cooling_detail_lines(hardware) -> list[str]:
    cooling_system = hardware.motherboard.cooling_system
    lines = [
        cooling_system.name,
        f"Manufacturer: {cooling_system.manufacturer}",
        f"Coolant: {cooling_system.coolant_type.value} ({cooling_system.coolant_amount}%)",
        "---",
        f"Current draw: {cooling_system.calc_current_power_usage():.0f}/{cooling_system.power_usage_watts_max} W",
        "---",
        f"Environment temperature: {cooling_system.env_temperature_celsius:.1f} C",
        f"Warning/Maximum temperature: {hardware.warning_temperature:.1f} / {hardware.critical_temperature:.1f} C",
        f"Maximum cooling factor at: {cooling_system.max_cooling_temperature_celsius:.1f} C",
        "---",
        f"System temperature: {hardware.temperature_celsius:.1f} C",
        f"Cooling power: {cooling_system.calculate_cooling_power():.1f} ",
    ]
    return lines


def _cooling_options(hardware) -> list[SettingOption]:
    """Live-tunable knobs shown in the Cooling detail screen's top-right box
    (see DetailScreen's `options`) -- each edit mutates the real hardware
    state directly, so it immediately feeds into the next power/temperature
    tick, same as if these values had been their defaults all along."""
    cooling_system = hardware.motherboard.cooling_system

    def adjust_max_cooling_temperature(delta: float) -> None:
        cooling_system.max_cooling_temperature_celsius = max(
            cooling_system.env_temperature_celsius + 1.0, cooling_system.max_cooling_temperature_celsius + delta)

    def adjust_max_power_draw(delta: int) -> None:
        cooling_system.power_usage_watts_max = max(10, cooling_system.power_usage_watts_max + delta)

    def adjust_warning_temperature(delta: float) -> None:
        hardware.warning_temperature = max(
            0.0, min(hardware.critical_temperature - 1.0, hardware.warning_temperature + delta))

    def toggle_active() -> None:
        cooling_system.active = not cooling_system.active

    return [
        SettingOption("Maximum cooling factor at",
                      get_value=lambda: f"{cooling_system.max_cooling_temperature_celsius:.0f} C",
                      on_left=lambda: adjust_max_cooling_temperature(-5.0),
                      on_right=lambda: adjust_max_cooling_temperature(5.0)),
        SettingOption("Maximum power draw",
                      get_value=lambda: f"{cooling_system.power_usage_watts_max} W",
                      on_left=lambda: adjust_max_power_draw(-10),
                      on_right=lambda: adjust_max_power_draw(10)),
        SettingOption("Warning temperature",
                      get_value=lambda: f"{hardware.warning_temperature:.0f} C",
                      on_left=lambda: adjust_warning_temperature(-5.0),
                      on_right=lambda: adjust_warning_temperature(5.0)),
        SettingOption("Status",
                      get_value=lambda: "Active" if cooling_system.active else "Inactive",
                      on_left=toggle_active, on_right=toggle_active),
    ]


def _network_detail_lines(hardware) -> list[str]:
    interfaces = hardware.motherboard.network_interfaces
    if not interfaces:
        return ["No network interfaces."]
    lines = []
    for iface in interfaces:
        if lines:
            lines.append("")
        lines.extend([
            iface.name,
            f"MAC: {iface.mac_address}",
            f"IP: {iface.ip_address}",
            f"Manufacturer: {iface.manufacturer}",
            f"Power: {iface.power_usage_watts} W",
        ])
    return lines


def _push_detail_screen(ctx, title: str, lines_fn, history_fn=None, history_title: str = "History",
                         history_y_label: str = "Value", history_markers_fn=None,
                         options: list[SettingOption] | None = None, status_fn=None) -> None:
    """Opens a live-refreshing DetailScreen for one component --
    `lines_fn` is called both now (initial render) and again on every
    refresh tick, so it must stay cheap and side-effect free. `history_fn`,
    if given, is the same idea for a MetricHistory.values()-shaped line
    graph (see DetailScreen) instead of a second text panel. `options`, if
    given, fills the graph's otherwise-empty top-right box with live-tunable
    settings (see DetailScreen). `status_fn`, if given, is pinned to its own
    bar at the bottom of the left panel instead of scrolling with `lines`."""
    ctx.screens.push(DetailScreen(ctx.screen, title, lines_fn(), ctx.screens, refresh=lines_fn,
                                   history_fn=history_fn, history_title=history_title,
                                   history_y_label=history_y_label, history_markers_fn=history_markers_fn,
                                   options=options, status_fn=status_fn))


def _build_hardware_screen(ctx) -> tuple[HardwareScreen, dict[str, HardwareTile]]:
    """Assembles the hardware overview from live data: HardwareSpec for the
    machine's static specs, ProcessTable for how much of its CPU/RAM budget
    is currently in use. Storage shows the installed drives' specs, same as
    Network -- it just has no live usage percentage the way CPU/RAM do,
    since there's no I/O simulation to derive one from.

    CPU/RAM load (and, downstream, PSU draw) can change every tick, so
    those tiles -- and the Overview summary at the top -- are kept current
    the same way TopScreen keeps `top` live: refresh() below re-derives
    their `.lines` from `table`/`hardware` on every HardwareScreen tick,
    not just once at push time.

    Each tile's on_select opens the matching DetailScreen (see
    _push_detail_screen) -- more room than a small tile has for details, and
    kept just as live via its own refresh callback. Returns the tiles
    keyed by the names in _TILE_FLAGS too, so sys() can jump straight to
    one of them (its on_select is exactly what Enter would trigger on it)."""
    hardware = ctx.hardware if ctx.hardware is not None else HardwareSpec()
    table = ctx.process_table

    overview = HardwareTile("Overview")
    cpu = HardwareTile("CPU", on_select=lambda: _push_detail_screen(ctx, "CPU", lambda: _cpu_detail_lines(hardware, table)))
    ram = HardwareTile("RAM", on_select=lambda: _push_detail_screen(ctx, "RAM", lambda: _ram_detail_lines(hardware, table)))
    storage = HardwareTile("Storage", on_select=lambda: _push_detail_screen(ctx, "Storage", lambda: _storage_detail_lines(hardware)))
    external = HardwareTile("External")
    power = HardwareTile("Power", on_select=lambda: _push_detail_screen(ctx, "Power", lambda: _power_detail_lines(hardware)))
    cooling = HardwareTile("Cooling", on_select=lambda: _push_detail_screen(
        ctx, "Cooling", lambda: _cooling_detail_lines(hardware),
        history_fn=lambda: hardware.temperature_history.values(),
        history_title="Temperature History", history_y_label="Temp",
        history_markers_fn=lambda: [hardware.motherboard.cooling_system.env_temperature_celsius,
                                     hardware.warning_temperature, hardware.critical_temperature],
        options=_cooling_options(hardware), status_fn=lambda: _cooling_status(hardware)))
    network = HardwareTile("Network", on_select=lambda: _push_detail_screen(ctx, "Network", lambda: _network_detail_lines(hardware)))

    def refresh() -> None:
        overview.lines = [format_system_summary(table, hardware)]

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

        drives = hardware.installed_storage()
        storage.lines = [f"{drive.name}: {drive.size} KB" for drive in drives] or ["No drives detected."]

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
            f"Cooling power: {cooling_system.calculate_cooling_power():.0f}",
            f"Draw: {cooling_system.calc_current_power_usage():.0f}/{cooling_system.power_usage_watts_max} W",
        ]

        interfaces = hardware.motherboard.network_interfaces
        network.lines = [f"{iface.name}: {iface.ip_address}" for iface in interfaces] or ["No network interfaces."]

    refresh()  # populate before the first render

    screen = HardwareScreen(ctx.screen, "System Overview", overview, cpu, ram, storage,
                             external, power, cooling, network, ctx.screens, refresh=refresh)
    tiles = {"cpu": cpu, "ram": ram, "storage": storage, "power": power, "cooling": cooling, "network": network}
    return screen, tiles


@command("sys", help_text="Show a hardware overview")
def sys(ctx, argv: list[str]) -> None:
    try:
        args = _sys_parser.parse_args(argv)
    except CommandParseError as e:
        ctx.write_line(e.message or e.usage)
        return

    screen, tiles = _build_hardware_screen(ctx)
    ctx.screens.push(screen)

    for name, tile in tiles.items():
        if getattr(args, name):
            tile.on_select()
            break
