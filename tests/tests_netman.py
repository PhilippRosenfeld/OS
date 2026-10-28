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
    return NetDaemon(hardware, processes, port_table=port_table), processes


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


# --- ports and usage ---

def test_ports_lists_every_open_port_with_its_process(netman_with_ports):
    run, _ = netman_with_ports
    lines = run("ports").splitlines()
    assert "Protocol" in lines[0] and "PID" in lines[0]
    assert any(line.split()[:2] == ["tcp", "22"] and "ssh" in line for line in lines)
    assert any(line.split()[:3] == ["tcp", "8080", "192.168.9.9"] for line in lines)
    assert any(line.split()[:2] == ["udp", "5353"] for line in lines)


def test_ports_without_any_open_port():
    buffer = ScreenBuffer(80, 5)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, hardware=HardwareSpec(), port_table=PortTable())
    Kernel(registry=netman_commands, bus=EventBus()).execute("ports", ctx)
    assert "No open ports." in full_text(buffer)


@pytest.mark.parametrize("line,usage", [
    ("iface", "Usage: iface <interface_name>"),
    ("up", "Usage: up <interface_name>"),
    ("down", "Usage: down <interface_name>"),
    ("set-ip eth0", "Usage: set-ip <interface_name> <ip_address>"),
])
def test_commands_without_enough_arguments_show_their_usage(netman, line, usage):
    run, hardware, _ = netman
    before = vars(eth0(hardware)).copy()
    assert usage in run(line)
    assert vars(eth0(hardware)) == before


def test_iface_matches_ports_against_the_interfaces_current_ip(netman_with_ports):
    run, hardware = netman_with_ports
    hardware.motherboard.network_interfaces[0].ip_address = "10.9.9.9"
    out = run("iface eth0")
    assert "ssh" in out                      # bound to every interface, so still there
    assert "mdns" not in out                 # was bound to the old IP


def test_iface_without_reachable_ports_says_none():
    buffer = ScreenBuffer(80, 20)
    hardware = HardwareSpec()
    ports = PortTable()
    ports.add(Listener("tcp", 8080, pid=1, service="other-nic", address="192.168.9.9"))
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, hardware=hardware, port_table=ports)
    Kernel(registry=netman_commands, bus=EventBus()).execute("iface eth0", ctx)
    assert "Ports: none" in full_text(buffer)
    assert "other-nic" not in full_text(buffer)


# --- ping ---

@pytest.fixture
def pinger():
    """netman with netd running and a host table; returns (run, hardware, hosts, kill_netd)."""
    from horus.network.hosts import HostEntry, HostTable
    buffer = ScreenBuffer(100, 40)
    hardware = HardwareSpec()
    hosts = HostTable({"files.test": HostEntry(name="files.test", ip="10.0.0.5", latency_ms=20.0)})
    processes = ProcessTable()
    processes.add_process(Process(name="netd", pid=0, owner="root"))
    netd = NetDaemon(hardware, processes, hosts=hosts)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, hardware=hardware, netd=netd,
                  host_table=hosts)
    kernel = Kernel(registry=netman_commands, bus=EventBus())

    def run(line):
        buffer.clear()
        buffer.cursor_row, buffer.cursor_col = 0, 0
        kernel.execute(line, ctx)
        return full_text(buffer)

    def kill_netd():
        processes.remove_process(processes.get_process_by_name("netd").pid, user="root", role=UserRole.ROOT)

    return run, hardware, hosts, kill_netd


def replies(out):
    return sum(line.startswith("Reply from") for line in out.splitlines())


def test_ping_a_known_host_by_name_gets_replies_with_its_latency(pinger):
    run, hardware, _, _ = pinger
    out = run("ping files.test")
    assert "Pinging files.test [10.0.0.5] via eth0" in out
    assert replies(out) == 4
    assert "Sent = 4, Received = 4, Lost = 0 (0% loss)" in out
    times = [int(line.split("time=")[1].split("ms")[0]) for line in out.splitlines() if "time=" in line]
    expected = eth0(hardware).latency_ms + 20.0           # interface + host latency, +-20 % (and rounding)
    assert all(int(expected * 0.8) <= t <= round(expected * 1.2) for t in times)


def test_ping_count_is_configurable_and_capped(pinger):
    run, _, _, _ = pinger
    assert replies(run("ping files.test 2")) == 2
    assert replies(run("ping files.test 999")) == 20


@pytest.mark.parametrize("line", ["ping", "ping a b c", "ping files.test lots"])
def test_ping_with_bad_arguments_shows_its_usage(pinger, line):
    run, _, _, _ = pinger
    assert "Usage: ping <hostname_or_ip> [count]" in run(line)


def test_ping_an_unknown_name(pinger):
    run, _, _, _ = pinger
    assert "ping: unknown host 'nowhere.test'" in run("ping nowhere.test")


def test_ping_by_name_needs_netd_but_by_ip_does_not(pinger):
    run, _, _, kill_netd = pinger
    kill_netd()
    assert "cannot resolve 'files.test': netd is not running" in run("ping files.test")
    assert replies(run("ping 10.0.0.5")) == 4


def test_ping_an_offline_or_unknown_ip_times_out(pinger):
    run, _, hosts, _ = pinger
    hosts.get_host("files.test").online = False
    out = run("ping 10.0.0.5")
    assert replies(out) == 0 and out.count("Request timed out.") == 4
    assert "Lost = 4 (100% loss)" in out and "Round trip" not in out
    assert replies(run("ping 10.9.9.9")) == 0


def test_ping_needs_an_interface_that_is_up(pinger):
    run, hardware, _, _ = pinger
    eth0(hardware).enabled = False
    out = run("ping 10.0.0.5")
    assert "Network is unreachable" in out and replies(out) == 0


def test_ping_drops_packets_by_the_interfaces_packet_loss(pinger):
    run, hardware, _, _ = pinger
    eth0(hardware).packet_loss_percentage = 100.0
    assert "Lost = 4 (100% loss)" in run("ping files.test")


def test_ping_the_own_address_answers(pinger):
    run, hardware, _, _ = pinger
    assert replies(run(f"ping {eth0(hardware).ip_address}")) == 4
    assert replies(run("ping 127.0.0.1")) == 4
