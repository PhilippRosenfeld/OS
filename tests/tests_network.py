import dataclasses

import pytest

from horus.events.bus import EventBus
from horus.network.listener import ANY_ADDRESS, Listener
from horus.network.port_table import (
    EPHEMERAL_PORTS,
    NoSuchProcessError,
    PortAccessDeniedError,
    PortError,
    PortInUseError,
    PortTable,
)
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable
from horus.session.user import UserRole

ROOT = UserRole.ROOT


# --- Listener ---

def test_listener_defaults_to_every_interface():
    assert Listener("tcp", 22, pid=1, service="ssh").address == ANY_ADDRESS


@pytest.mark.parametrize("protocol,port", [("TCP", 22), ("icmp", 22), ("tcp", -1), ("udp", 65536)])
def test_listener_rejects_unknown_protocols_and_out_of_range_ports(protocol, port):
    with pytest.raises(ValueError):
        Listener(protocol, port, pid=1, service="x")


def test_listener_accepts_the_full_port_range():
    assert Listener("udp", 0, pid=1, service="x").port == 0
    assert Listener("udp", 65535, pid=1, service="x").port == 65535


def test_listener_cannot_be_changed_once_created():
    listener = Listener("tcp", 22, pid=1, service="ssh")
    with pytest.raises(dataclasses.FrozenInstanceError):
        listener.port = 80


# --- PortTable: adding ---

def make_table(process_count=3):
    """A PortTable checking against a process table holding PIDs 1..process_count."""
    processes = ProcessTable(events=EventBus())
    for i in range(process_count):
        processes.add_process(Process(name=f"p{i + 1}", pid=0))
    return PortTable(processes, events=processes._events), processes


def test_add_and_find_a_port():
    table, _ = make_table()
    ssh = table.add(Listener("tcp", 22, pid=1, service="ssh"), role=ROOT)
    assert table.find("tcp", 22, "10.0.0.2") is ssh       # bound to all interfaces -> reachable on any
    assert table.is_open("tcp", 22) and len(table) == 1


def test_tcp_and_udp_on_the_same_number_are_separate_ports():
    table, _ = make_table()
    table.add(Listener("tcp", 53, pid=1, service="dns"), role=ROOT)
    table.add(Listener("udp", 53, pid=1, service="dns"), role=ROOT)
    assert len(table) == 2


def test_the_same_port_on_two_interfaces_is_allowed():
    table, _ = make_table()
    a = table.add(Listener("tcp", 8080, pid=1, service="a", address="10.0.0.2"))
    b = table.add(Listener("tcp", 8080, pid=2, service="b", address="10.0.1.2"))
    assert table.find("tcp", 8080, "10.0.0.2") is a
    assert table.find("tcp", 8080, "10.0.1.2") is b


def test_the_same_binding_twice_is_refused():
    table, _ = make_table()
    table.add(Listener("tcp", 8080, pid=1, service="a"))
    with pytest.raises(PortInUseError) as error:
        table.add(Listener("tcp", 8080, pid=2, service="b"))
    assert "'a' (PID 1)" in str(error.value)


def test_binding_every_interface_conflicts_with_a_single_interface_binding_and_vice_versa():
    table, _ = make_table()
    table.add(Listener("tcp", 8080, pid=1, service="a", address="10.0.0.2"))
    with pytest.raises(PortInUseError):
        table.add(Listener("tcp", 8080, pid=2, service="b"))

    other, _ = make_table()
    other.add(Listener("tcp", 8080, pid=1, service="a"))
    with pytest.raises(PortInUseError):
        other.add(Listener("tcp", 8080, pid=2, service="b", address="10.0.0.2"))


def test_privileged_ports_need_admin_rights():
    table, _ = make_table()
    with pytest.raises(PortAccessDeniedError):
        table.add(Listener("tcp", 80, pid=1, service="http"))                  # USER by default
    table.add(Listener("tcp", 80, pid=1, service="http"), role=UserRole.ADMIN)
    table.add(Listener("tcp", 1024, pid=1, service="dev"))                     # first unprivileged port
    assert len(table) == 2


def test_ports_need_an_existing_process():
    table, _ = make_table()
    with pytest.raises(NoSuchProcessError):
        table.add(Listener("tcp", 8080, pid=99, service="ghost"))


def test_without_a_process_table_any_pid_is_accepted():
    table = PortTable()
    table.add(Listener("tcp", 8080, pid=99, service="x"))
    assert len(table) == 1


def test_every_refusal_is_a_port_error():
    assert issubclass(PortInUseError, PortError)
    assert issubclass(PortAccessDeniedError, PortError)
    assert issubclass(NoSuchProcessError, PortError)


# --- PortTable: lookups and removal ---

def test_find_prefers_an_exact_binding_over_every_interface():
    table, _ = make_table()
    exact = table.add(Listener("udp", 5000, pid=1, service="exact", address="10.0.0.2"))
    assert table.find("udp", 5000, "10.0.0.2") is exact
    assert table.find("udp", 5000, "10.0.1.2") is None
    assert table.find("tcp", 5000, "10.0.0.2") is None


def test_remove_closes_one_port():
    table, _ = make_table()
    table.add(Listener("tcp", 8080, pid=1, service="a"))
    assert table.remove("tcp", 8080)
    assert not table.remove("tcp", 8080)
    assert len(table) == 0


def test_a_dying_process_closes_all_its_ports():
    table, processes = make_table()
    table.add(Listener("tcp", 8080, pid=1, service="a"))
    table.add(Listener("udp", 8081, pid=1, service="a"))
    table.add(Listener("tcp", 9000, pid=2, service="b"))
    processes.remove_process(1, user="root", role=ROOT)
    assert [listener.port for listener in table.list()] == [9000]


def test_list_is_a_sorted_copy_and_can_filter_by_protocol():
    table, _ = make_table()
    table.add(Listener("udp", 9000, pid=1, service="b"))
    table.add(Listener("tcp", 8080, pid=1, service="a"))
    listed = table.list()
    assert [listener.port for listener in listed] == [8080, 9000]
    listed.clear()
    assert len(table) == 2                                  # the table itself is untouched
    assert [listener.protocol for listener in table.list("udp")] == ["udp"]


def test_ephemeral_ports_skip_taken_ones():
    table, _ = make_table()
    first = EPHEMERAL_PORTS[0]
    assert table.allocate_ephemeral("tcp") == first
    table.add(Listener("tcp", first, pid=1, service="taken"))
    assert table.allocate_ephemeral("tcp") == first + 1
    assert table.allocate_ephemeral("udp") == first          # other protocol, other number space


# --- system services open their ports at startup ---

def test_seeded_services_listen_on_their_ports_and_close_them_when_killed():
    from horus.processes.seed_process import seed_processes
    bus = EventBus()
    processes = ProcessTable(events=bus)
    table = PortTable(processes, events=bus)
    seed_processes(processes, table)

    opened = {(listener.protocol, listener.port): listener for listener in table.list()}
    assert set(opened) == {("udp", 53), ("udp", 514)}
    netd = next(proc for proc in processes.list_processes() if proc.name == "netd")
    assert opened[("udp", 53)].pid == netd.pid and opened[("udp", 53)].service == "dns"

    processes.remove_process(netd.pid, user="root", role=ROOT)
    assert not table.is_open("udp", 53) and table.is_open("udp", 514)


def test_seeding_without_a_port_table_only_starts_the_processes():
    from horus.processes.seed_process import seed_processes
    processes = ProcessTable()
    seed_processes(processes)
    assert len(processes.list_processes()) == 10
