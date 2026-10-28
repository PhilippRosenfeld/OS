import pytest

from horus.events.bus import EventBus
from horus.hardware.spec import HardwareSpec
from horus.network.address import is_valid_ip
from horus.network.hosts import HostEntry, HostTable
from horus.network.netd import (
    NetDaemon,
    NetdError,
    NetdInterfaceNotFoundError,
    NetdInvalidConfigError,
    NetdNotRunningError,
)
from horus.network.port_table import PortInUseError, PortTable
from horus.processes.processTable import ProcessTable
from horus.processes.services import find_service, start_service
from horus.session.user import UserRole


@pytest.fixture
def system():
    """Hardware, a process table with netd started from its blueprint, a
    port table and a NetDaemon on top; returns (netd, hardware, processes, ports)."""
    bus = EventBus()
    hardware = HardwareSpec()
    processes = ProcessTable(events=bus)
    ports = PortTable(processes, events=bus)
    start_service(find_service("netd"), processes, ports)
    hosts = HostTable({"files.test": HostEntry(name="files.test", ip="10.0.0.5")})
    netd = NetDaemon(hardware, processes, hosts=hosts, port_table=ports)
    return netd, hardware, processes, ports


def eth0(hardware):
    return hardware.motherboard.network_interfaces[0]


def kill(processes, name):
    pid = next(p.pid for p in processes.list_processes() if p.name == name)
    processes.remove_process(pid, user="root", role=UserRole.ROOT)


@pytest.mark.parametrize("ip,valid", [("10.0.0.1", True), ("255.255.255.255", True), ("300.1.1.1", False),
                                      ("10.0.0", False), ("a.b.c.d", False), ("", False)])
def test_is_valid_ip(ip, valid):
    assert is_valid_ip(ip) is valid


def test_netd_runs_as_long_as_its_process_does(system):
    netd, _, processes, _ = system
    assert netd.is_running()
    kill(processes, "netd")
    assert not netd.is_running()


def test_interfaces_can_be_changed_while_netd_runs(system):
    netd, hardware, _, _ = system
    netd.set_enabled("eth0", False)
    netd.set_ip("eth0", "10.0.0.42")
    netd.set_speed("eth0", 100, 20)
    iface = eth0(hardware)
    assert (iface.enabled, iface.ip_address, iface.link_speed_down_mbps, iface.link_speed_up_mbps) == (False, "10.0.0.42", 100, 20)


def test_no_change_without_netd(system):
    netd, hardware, processes, _ = system
    kill(processes, "netd")
    before = vars(eth0(hardware)).copy()
    for change in (lambda: netd.set_enabled("eth0", False), lambda: netd.set_ip("eth0", "10.0.0.42"),
                   lambda: netd.set_speed("eth0", 1, 1)):
        with pytest.raises(NetdNotRunningError):
            change()
    assert vars(eth0(hardware)) == before
    assert netd.interface("eth0") is eth0(hardware)          # reading still works


def test_bad_values_and_unknown_interfaces_are_refused(system):
    netd, hardware, _, _ = system
    before = vars(eth0(hardware)).copy()
    with pytest.raises(NetdInvalidConfigError):
        netd.set_ip("eth0", "300.1.1.1")
    with pytest.raises(NetdInvalidConfigError):
        netd.set_speed("eth0", -5, 20)
    with pytest.raises(NetdInterfaceNotFoundError):
        netd.set_enabled("wlan9", True)
    assert vars(eth0(hardware)) == before


def test_every_refusal_is_a_netd_error():
    for error in (NetdNotRunningError, NetdInterfaceNotFoundError, NetdInvalidConfigError):
        assert issubclass(error, NetdError)


def test_resolve_needs_netd_for_names_but_not_for_ips(system):
    netd, _, processes, _ = system
    assert netd.resolve("files.test") == "10.0.0.5"
    assert netd.resolve("nowhere.local") is None
    kill(processes, "netd")
    assert netd.resolve("10.0.0.7") == "10.0.0.7"
    with pytest.raises(NetdNotRunningError):
        netd.resolve("files.test")


def test_a_restarted_netd_reopens_its_port_and_works_again(system):
    netd, _, processes, ports = system
    kill(processes, "netd")
    assert not ports.is_open("udp", 53)
    start_service(find_service("netd"), processes, ports)
    assert netd.is_running() and ports.is_open("udp", 53)
    netd.set_enabled("eth0", False)


def test_start_service_rolls_back_when_a_port_is_taken(system):
    _, _, processes, ports = system                      # netd already holds udp 53
    count = len(processes.list_processes())
    with pytest.raises(PortInUseError):
        start_service(find_service("netd"), processes, ports)
    assert len(processes.list_processes()) == count
    assert len(ports.list()) == 1


def test_find_service():
    assert find_service("netd").ports == (("udp", 53, "dns"),)
    assert find_service("nope") is None
