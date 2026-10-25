import pytest

from horus.apps.netman.commands import netman_commands
from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.hardware.spec import HardwareSpec
from horus.kernel.kernel import Kernel
from horus.session.context import Context


def full_text(buffer):
    return "\n".join("".join(buffer.get_cell(c, r).char for c in range(buffer.cols)) for r in range(buffer.rows))


@pytest.fixture
def netman():
    """Runs a netman command line against default hardware; returns (run, hardware, buffer)."""
    buffer = ScreenBuffer(80, 20)
    hardware = HardwareSpec()
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, hardware=hardware)
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
    assert "Interface: eth0" in out and f"IP Address: {eth0(hardware).ip_address}" in out
    assert "Interface 'wlan9' not found." in run("iface wlan9")


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
