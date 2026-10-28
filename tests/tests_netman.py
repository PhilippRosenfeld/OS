import pytest

from horus.apps.netman.commands import netman_commands
from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.hardware.spec import HardwareSpec
from horus.kernel.kernel import Kernel
from horus.network.listener import Listener
from horus.network.netd import NetDaemon
from horus.network.port_table import PortTable
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable
from horus.session.context import Context
from horus.session.user import UserRole


def full_text(buffer):
    return "\n".join("".join(buffer.get_cell(c, r).char for c in range(buffer.cols)) for r in range(buffer.rows))


def running_netd(hardware, port_table=None):
    """A NetDaemon whose netd process is running; returns (netd, process_table)."""
    processes = ProcessTable()
    processes.add_process(Process(name="netd", pid=0, owner="root"))
    return NetDaemon(hardware, processes, port_table), processes


@pytest.fixture
def netman():
    """Runs a netman command line against default hardware with netd running;
    returns (run, hardware, buffer)."""
    buffer = ScreenBuffer(80, 20)
    hardware = HardwareSpec()
    netd, _ = running_netd(hardware)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, hardware=hardware, netd=netd)
    kernel = Kernel(registry=netman_commands, bus=EventBus())

    def run(line):
        kernel.execute(line, ctx)
        return full_text(buffer)

    return run, hardware, buffer


def eth0(hardware):
    return hardware.motherboard.network_interfaces[0]


def test_status_lists_every_interface(netman):
    run, hardware, _ = netman
    assert f"eth0  {eth0(hardware).ip_address}  UP" in run("status")


def test_iface_shows_details_or_reports_an_unknown_interface(netman):
    run, hardware, _ = netman
    out = run("iface eth0")
    assert "Interface   | eth0" in out
    assert f"IP Address  | {eth0(hardware).ip_address}" in out
    assert f"MAC Address | {eth0(hardware).mac_address}" in out
    assert "Mbps (down/up)" in out and "Status      | UP" in out
    assert "Interface 'wlan9' not found." in run("iface wlan9")


@pytest.fixture
def netman_with_ports():
    """Like `netman`, plus a port table: one port on every interface, one
    on eth0's own IP, one on another interface's IP."""
    buffer = ScreenBuffer(80, 30)
    hardware = HardwareSpec()
    ports = PortTable()
    ports.add(Listener("tcp", 22, pid=1, service="ssh"), role=UserRole.ROOT)
    ports.add(Listener("udp", 5353, pid=1, service="mdns", address=eth0(hardware).ip_address))
    ports.add(Listener("tcp", 8080, pid=1, service="other-nic", address="192.168.9.9"))
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, hardware=hardware, port_table=ports)
    kernel = Kernel(registry=netman_commands, bus=EventBus())

    def run(line):
        kernel.execute(line, ctx)
        return full_text(buffer)

    return run, hardware


def test_iface_lists_only_the_ports_reachable_through_that_interface(netman_with_ports):
    run, _ = netman_with_ports
    out = run("iface eth0")
    assert "ssh" in out and "mdns" in out          # bound to all interfaces / to eth0's IP
    assert "other-nic" not in out                 # bound to a different interface's IP


def test_iface_shows_tcp_as_listen_udp_without_state_and_down_when_disabled(netman_with_ports):
    run, hardware = netman_with_ports
    out = run("iface eth0")
    assert any("22" in line and "LISTEN" in line for line in out.splitlines())
    assert any("5353" in line and "-" in line and "LISTEN" not in line for line in out.splitlines())
    eth0(hardware).enabled = False
    out = run("iface eth0")
    assert sum("DOWN" in line for line in out.splitlines() if "ssh" in line or "mdns" in line) == 2


def test_iface_without_a_port_table_still_shows_the_interface(netman):
    run, _, _ = netman
    out = run("iface eth0")
    assert "Interface   | eth0" in out and "Ports" not in out


def test_down_and_up_switch_the_interface(netman):
    run, hardware, _ = netman
    run("down eth0")
    assert eth0(hardware).enabled is False
    run("up eth0")
    assert eth0(hardware).enabled is True


def test_set_ip_accepts_valid_and_rejects_invalid_addresses(netman):
    run, hardware, _ = netman
    run("set-ip eth0 10.0.0.42")
    assert eth0(hardware).ip_address == "10.0.0.42"
    assert "Invalid IP address: 300.1.1.1" in run("set-ip eth0 300.1.1.1")
    assert eth0(hardware).ip_address == "10.0.0.42"


def test_speed_sets_the_link_speeds_as_numbers(netman):
    run, hardware, _ = netman
    assert "speed set to 100/20 Mbps" in run("speed eth0 100 20")
    assert eth0(hardware).link_speed_down_mbps == 100
    assert eth0(hardware).link_speed_up_mbps == 20


@pytest.mark.parametrize("line,message", [
    ("speed eth0 fast 20", "Usage: speed"),
    ("speed eth0 100", "Usage: speed"),
    ("speed eth0 -5 20", "must not be negative"),
    ("speed wlan9 100 20", "Interface 'wlan9' not found."),
])
def test_speed_rejects_bad_input_and_leaves_the_interface_alone(netman, line, message):
    run, hardware, _ = netman
    before = (eth0(hardware).link_speed_down_mbps, eth0(hardware).link_speed_up_mbps)
    assert message in run(line)
    assert (eth0(hardware).link_speed_down_mbps, eth0(hardware).link_speed_up_mbps) == before


# --- changes go through netd ---

@pytest.fixture
def netman_with_netd():
    """Like `netman`, but also hands out a way to kill netd."""
    buffer = ScreenBuffer(80, 30)
    hardware = HardwareSpec()
    netd, processes = running_netd(hardware)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, hardware=hardware, netd=netd)
    kernel = Kernel(registry=netman_commands, bus=EventBus())

    def run(line):
        kernel.execute(line, ctx)
        return full_text(buffer)

    def kill_netd():
        pid = next(p.pid for p in processes.list_processes() if p.name == "netd")
        processes.remove_process(pid, user="root", role=UserRole.ROOT)

    return run, hardware, kill_netd


@pytest.mark.parametrize("line", ["down eth0", "up eth0", "set-ip eth0 10.0.0.42", "speed eth0 100 20"])
def test_changes_are_refused_while_netd_is_not_running(netman_with_netd, line):
    run, hardware, kill_netd = netman_with_netd
    before = vars(eth0(hardware)).copy()
    kill_netd()
    assert "netd is not running" in run(line)
    assert vars(eth0(hardware)) == before


def test_reading_the_interfaces_works_without_netd(netman_with_netd):
    run, hardware, kill_netd = netman_with_netd
    kill_netd()
    assert f"eth0  {eth0(hardware).ip_address}  UP" in run("status")
    assert "Interface   | eth0" in run("iface eth0")


def test_changes_are_refused_without_a_netd_at_all():
    buffer = ScreenBuffer(80, 20)
    hardware = HardwareSpec()
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, hardware=hardware)
    Kernel(registry=netman_commands, bus=EventBus()).execute("down eth0", ctx)
    assert "netd is not running" in full_text(buffer)
    assert eth0(hardware).enabled is True


@pytest.mark.parametrize("line", ["up wlan9", "down wlan9", "set-ip wlan9 10.0.0.42"])
def test_changes_to_an_unknown_interface_are_reported(netman, line):
    run, _, _ = netman
    assert "Interface 'wlan9' not found." in run(line)
