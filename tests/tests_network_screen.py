from unittest.mock import patch

import pyglet
import pytest

from horus.apps.netman.screen import NetmanWindow
from horus.apps.window_manager import WindowManager
from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.hardware.spec import HardwareSpec
from horus.kernel.commands.cmd_net import netman as netman_command
from horus.kernel.commands.cmd_sys import sys as sys_command
from horus.network.hosts import HostTable
from horus.network.netd import NetDaemon
from horus.network.network_view import host_lines, port_lines, route_table_lines
from horus.network.port_table import PortTable
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable
from horus.processes.services import find_service, start_service
from horus.session.context import Context
from horus.session.user import UserRole
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.network_screen import NetworkScreen

key = pyglet.window.key


def screen_text(buffer):
    return "\n".join("".join(buffer.get_cell(c, r).char for c in range(buffer.cols)).rstrip()
                     for r in range(buffer.rows))


@pytest.fixture(autouse=True)
def no_clock():
    with patch("pyglet.clock.schedule_interval"), patch("pyglet.clock.unschedule"):
        yield


@pytest.fixture
def system():
    """A machine with netd running (holding udp 53) and the standard hosts;
    returns (ctx, buffer, hardware, processes)."""
    buffer = ScreenBuffer(130, 40)
    hardware = HardwareSpec()
    bus = EventBus()
    processes = ProcessTable(total_memory_kb=hardware.total_memory_kb(), total_cpu_mhz=hardware.total_cpu_mhz(),
                             events=bus)
    ports = PortTable(processes, events=bus)
    start_service(find_service("netd"), processes, ports)
    hosts = HostTable()
    netd = NetDaemon(hardware, processes, hosts=hosts, port_table=ports)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, screens=ScreenManager(), events=bus,
                  process_table=processes, hardware=hardware, netd=netd, host_table=hosts, port_table=ports)
    return ctx, buffer, hardware, processes


def eth0(hardware):
    return hardware.motherboard.network_interfaces[0]


def kill(processes, name):
    processes.remove_process(processes.get_process_by_name(name).pid, user="root", role=UserRole.ROOT)


def netman_processes(processes):
    return [p for p in processes.list_processes() if p.name == "netman"]


def open_network_screen(ctx, buffer):
    sys_command(ctx, ["-n"])
    assert isinstance(ctx.screens.active, NetworkScreen)
    return screen_text(buffer)


def type_line(screen, line):
    screen.handle_text(line)
    screen.handle_enter()


def row_of(rows, text):
    return next(i for i, row in enumerate(rows) if text in row)


# --- the panel ---

def test_the_network_screen_shows_netd_the_gateway_and_each_interface(system):
    ctx, buffer, hardware, _ = system
    text = open_network_screen(ctx, buffer)
    iface = eth0(hardware)
    assert "netd: running" in text and "Gateway: 192.168.1.10" in text
    assert f"{iface.name} (UP)" in text and f"MAC: {iface.mac_address}" in text
    assert f"IP: {iface.ip_address}/{iface.netmask_length}" in text and f"Network: {iface.network}" in text
    assert "Status: ONLINE" in text


def test_the_traffic_box_shows_the_load_against_the_link_speed(system):
    ctx, buffer, hardware, _ = system
    iface = eth0(hardware)
    iface.link_speed_down_mbps, iface.link_speed_up_mbps = 100, 20
    iface.load_down, iface.load_up = 0.5, 0.25
    text = open_network_screen(ctx, buffer)
    assert "eth0 (UP) down  50/100 Mbps (50.0%)" in text
    assert "Up: 5.0/20 Mbps" in text


def test_netman_sits_right_under_a_small_traffic_box(system):
    ctx, buffer, _, _ = system
    rows = open_network_screen(ctx, buffer).splitlines()
    assert row_of(rows, "+ Traffic -") == 0
    assert row_of(rows, "+ Connection Manager -") == 6     # one interface: border, padding, 3 rows, border
    assert "net>" in rows[row_of(rows, "Type 'help' for commands.") + 2]


def test_a_stopped_netd_blinks_in_the_status_bar(system):
    ctx, buffer, _, processes = system
    kill(processes, "netd")
    text = open_network_screen(ctx, buffer)
    assert "netd: stopped" in text and "NETD STOPPED" in text


def test_all_interfaces_down_is_offline(system):
    ctx, buffer, hardware, _ = system
    eth0(hardware).enabled = False
    text = open_network_screen(ctx, buffer)
    assert "Status: OFFLINE" in text and "eth0 (DOWN)" in text


def test_the_screen_works_without_any_network_services():
    """A bare context (no netd, ports or hosts) still opens the screen."""
    buffer = ScreenBuffer(130, 40)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, screens=ScreenManager(),
                  process_table=ProcessTable(), hardware=HardwareSpec())
    text = open_network_screen(ctx, buffer)
    assert "netd: stopped" in text and "Gateway: -" in text and "net>" in text


def test_the_overview_tile_shows_the_interface_its_ip_and_its_load(system):
    ctx, buffer, hardware, _ = system
    iface = eth0(hardware)
    iface.link_speed_down_mbps, iface.load_down = 100, 0.25
    sys_command(ctx, [])
    text = screen_text(buffer)
    assert "eth0 (UP)" in text and f"IP: {iface.ip_address}/24" in text
    assert "Load: 25.0/100 Mbps (25%)" in text


def test_the_overview_tile_shows_a_stopped_netd_on_its_first_line(system):
    ctx, buffer, _, processes = system
    kill(processes, "netd")
    sys_command(ctx, [])
    assert "eth0 (UP), netd stopped" in screen_text(buffer)


# --- netman in the box ---

def test_commands_typed_in_the_box_run_in_netman(system):
    ctx, buffer, _, _ = system
    open_network_screen(ctx, buffer)
    type_line(ctx.screens.active, "route")
    assert "default            192.168.1.10    eth0   UP" in screen_text(buffer)


def test_a_command_in_the_box_shows_up_in_the_panel_right_away(system):
    ctx, buffer, hardware, _ = system
    open_network_screen(ctx, buffer)
    type_line(ctx.screens.active, "down eth0")
    text = screen_text(buffer)
    assert not eth0(hardware).enabled
    assert "eth0 (DOWN)" in text and "Status: OFFLINE" in text


def test_the_cursor_sits_in_the_box_after_the_prompt(system):
    ctx, buffer, _, _ = system
    rows = open_network_screen(ctx, buffer).splitlines()
    assert buffer.cursor_enabled
    assert rows[buffer.cursor_row][buffer.cursor_col - 5:buffer.cursor_col] == "net> "
    assert buffer.cursor_col > buffer.cols // 3                 # in the right half, not the panel


def test_netman_runs_as_its_process_and_keeps_running_after_the_screen_closes(system):
    ctx, buffer, _, processes = system
    open_network_screen(ctx, buffer)
    screen = ctx.screens.active
    assert len(netman_processes(processes)) == 1
    screen.handle_key(key.ESCAPE, 0)
    assert ctx.screens.active is not screen                     # Escape closes the screen, not netman
    assert len(netman_processes(processes)) == 1
    assert ctx.background_apps["netman"].is_open


def test_the_box_and_the_window_are_the_same_session(system):
    ctx, buffer, _, processes = system
    open_network_screen(ctx, buffer)
    type_line(ctx.screens.active, "hosts")
    window = ctx.background_apps["netman"]
    ctx.screens.active.handle_key(key.ESCAPE, 0)                # back to the overview
    ctx.screens.pop()                                            # and out of sys

    netman_command(ctx, [])                                      # the window shows the same shell
    manager = ctx.screens.active
    assert isinstance(manager, WindowManager) and manager.focused is window
    assert "mainframe.corp" in screen_text(window.shell_buffer)
    assert len(netman_processes(processes)) == 1


def test_a_netman_shown_in_its_window_moves_into_the_box(system):
    ctx, buffer, _, processes = system
    netman_command(ctx, [])
    manager = ctx.screens.active
    window = manager.focused
    type_line(manager, "ports")

    text = open_network_screen(ctx, buffer)
    assert window not in manager.windows and window.attached     # taken out of the window manager
    assert ctx.screens.active.app is window
    assert "udp        53" in text                              # with what it printed there
    assert len(netman_processes(processes)) == 1


def test_exit_in_the_box_hides_netman_and_enter_brings_it_back(system):
    ctx, buffer, _, processes = system
    open_network_screen(ctx, buffer)
    screen = ctx.screens.active
    window = screen.app
    type_line(screen, "exit")
    assert screen.app is None and "Press Enter to show it here." in screen_text(buffer)
    assert len(netman_processes(processes)) == 1
    screen.handle_enter()
    assert screen.app is window and "net>" in screen_text(buffer)


def test_quitting_or_killing_netman_leaves_a_hint_and_enter_starts_a_new_one(system):
    ctx, buffer, _, processes = system
    open_network_screen(ctx, buffer)
    screen = ctx.screens.active
    kill(processes, "netman")
    assert screen.app is None and "netman is not running." in screen_text(buffer)
    screen.handle_enter()
    assert isinstance(screen.app, NetmanWindow) and len(netman_processes(processes)) == 1
    type_line(screen, "quit")
    assert screen.app is None and netman_processes(processes) == []


def test_ctrl_c_stops_a_ping_running_in_the_box(system):
    ctx, buffer, _, _ = system
    open_network_screen(ctx, buffer)
    screen = ctx.screens.active
    with patch("pyglet.clock.schedule_once"):
        type_line(screen, "ping gateway")
        assert screen.app.input.busy
        screen.handle_key(key.C, key.MOD_CTRL)
    assert not screen.app.input.busy and "^C" in screen_text(buffer)
    assert ctx.screens.active is screen


# --- traffic simulation ---

def sync(hardware, processes):
    hardware._process_table = processes
    hardware._sync_component_load_from_process_table()


def test_an_up_interface_carries_traffic_that_grows_with_the_cpu_load(system):
    _, _, hardware, processes = system
    idle = []
    for _ in range(50):
        sync(hardware, processes)
        idle.append(eth0(hardware).load_down)
    processes.add_process(Process(name="busy", pid=99, owner="root", cpu_mhz=processes.total_cpu_mhz))
    busy = []
    for _ in range(50):
        sync(hardware, processes)
        busy.append(eth0(hardware).load_down)
    assert all(0.0 <= load <= 1.0 for load in idle + busy)
    assert sum(busy) / len(busy) > sum(idle) / len(idle) + 0.2


def test_a_down_interface_carries_nothing(system):
    _, _, hardware, processes = system
    eth0(hardware).enabled = False
    eth0(hardware).load_down = eth0(hardware).load_up = 0.7
    sync(hardware, processes)
    assert (eth0(hardware).load_down, eth0(hardware).load_up) == (0.0, 0.0)


# --- the shared tables ---

def test_the_tables_handle_missing_services():
    assert port_lines(None) == ["No open ports."]
    assert host_lines(None) == ["No known hosts."]
    assert len(route_table_lines(HardwareSpec(), None)) == 3     # header, rule, eth0 -- no default route


def test_hosts_are_listed_by_name_with_their_state():
    hosts = HostTable()
    hosts.get_host("server.local").online = False
    rows = host_lines(hosts)[2:]
    assert [row.split()[0] for row in rows] == ["gateway", "mainframe.corp", "server.local"]
    assert rows[2].endswith("offline")


# --- formatting ---

def test_the_traffic_bar_spans_the_whole_box_without_an_icon(system):
    ctx, buffer, _, _ = system
    rows = open_network_screen(ctx, buffer).splitlines()
    bar_row = rows[row_of(rows, "eth0 (UP) down") + 1]
    box_left = rows[0].index("+ Traffic")
    assert bar_row.index("[") == box_left + 2                   # right after the padding, no icon gap
    assert bar_row.index("]") == len(rows[0]) - 3               # up to the padding on the right


def test_the_panel_widens_so_its_lines_are_not_cut_off(system):
    ctx, _, hardware, _ = system
    ctx.screen = buffer = ScreenBuffer(80, 40)
    text = open_network_screen(ctx, buffer)
    assert f"Network: {eth0(hardware).network}" in text and "Latency: 50 ms   Loss: 0%" in text


def test_help_wraps_long_texts_aligned_under_themselves_in_a_narrow_box(system):
    ctx, _, _, _ = system
    ctx.screen = buffer = ScreenBuffer(80, 40)
    open_network_screen(ctx, buffer)
    screen = ctx.screens.active
    type_line(screen, "help")
    shell = screen.app.shell_buffer
    rows = [line for line in screen_text(shell).splitlines()]
    down = row_of(rows, "  down    Bring down")
    assert rows[down + 1].startswith(" " * 10) and rows[down + 1].strip() == "interface"
    assert all(len(row) < shell.cols for row in rows)


# --- netman one font size smaller ---

class FakeWindow:
    """What NetworkScreen's font scale is derived from: the glyph size."""

    def __init__(self, char_width):
        self.char_width, self.char_height = char_width, char_width * 2


def test_netman_is_one_font_size_smaller_than_the_panel(system):
    ctx, buffer, _, _ = system
    ctx.window = FakeWindow(32)                                  # font size 4 -> netman at 3
    open_network_screen(ctx, buffer)
    screen = ctx.screens.active
    x, y, width, height = screen._app_rect()
    inset = buffer.inset
    assert inset.buffer is screen.app.surface and (inset.col, inset.row, inset.cols, inset.rows) == (x, y, width, height)
    assert screen.app.size == (int(width * 4 / 3), int(height * 4 / 3))
    assert "net>" in screen_text(screen.app.surface)
    assert not buffer.cursor_enabled and screen.app.surface.cursor_enabled   # the cursor is the inset's


def test_netman_keeps_the_panels_font_size_at_the_smallest_step_or_without_a_window(system):
    ctx, buffer, _, _ = system
    ctx.window = FakeWindow(8)
    open_network_screen(ctx, buffer)
    assert buffer.inset is None and "net>" in screen_text(buffer)


def test_the_inset_is_gone_once_the_screen_closes(system):
    ctx, buffer, _, _ = system
    ctx.window = FakeWindow(32)
    open_network_screen(ctx, buffer)
    ctx.screens.active.handle_key(key.ESCAPE, 0)
    assert buffer.inset is None
