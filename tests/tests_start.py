import pytest

from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.kernel.commands.cmd_proc import start
from horus.network.port_table import PortTable
from horus.processes.processTable import ProcessTable
from horus.processes.services import _SYSTEM_PROCESSES, find_service, start_service
from horus.session.context import Context
from horus.session.user import UserRole


def full_text(buffer):
    return "\n".join("".join(buffer.get_cell(c, r).char for c in range(buffer.cols)) for r in range(buffer.rows))


@pytest.fixture
def system():
    """A context with an empty process table and a port table on the same bus;
    returns (run, processes, ports). run(argv) clears the screen first, so it
    returns only what that one call printed."""
    buffer = ScreenBuffer(80, 20)
    bus = EventBus()
    processes = ProcessTable(events=bus)
    ports = PortTable(processes, events=bus)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, process_table=processes, port_table=ports)

    def run(*argv):
        buffer.clear()
        buffer.cursor_row, buffer.cursor_col = 0, 0
        start(ctx, list(argv))
        return full_text(buffer)

    return run, processes, ports


def kill(processes, name):
    pid = processes.get_process_by_name(name).pid
    processes.remove_process(pid, user="root", role=UserRole.ROOT)


# --- starting a service ---

def test_start_runs_the_service_and_opens_its_ports(system):
    run, processes, ports = system
    out = run("netd")
    netd = processes.get_process_by_name("netd")
    assert netd is not None
    assert f"Started service 'netd' (PID {netd.pid})" in out
    assert ports.find("udp", 53, "10.0.0.2").pid == netd.pid      # bound to every interface


def test_started_process_matches_its_blueprint(system):
    run, processes, _ = system
    run("syslogd")
    proc, spec = processes.get_process_by_name("syslogd"), find_service("syslogd")
    assert (proc.owner, proc.mem_kb, proc.critical) == (spec.owner, spec.mem_kb, spec.critical)


def test_a_service_without_ports_starts_too(system):
    run, processes, ports = system
    assert "Started service 'crond'" in run("crond")
    assert processes.get_process_by_name("crond") is not None
    assert len(ports.list()) == 0


def test_a_killed_service_can_be_started_again(system):
    run, processes, ports = system
    run("netd")
    kill(processes, "netd")
    assert not ports.is_open("udp", 53)
    assert "Started service 'netd'" in run("netd")
    assert ports.is_open("udp", 53)


def test_starting_a_running_service_is_refused(system):
    run, processes, ports = system
    run("netd")
    assert "start: 'netd' - Service is already running" in run("netd")
    assert sum(p.name == "netd" for p in processes.list_processes()) == 1
    assert len(ports.list()) == 1


def test_an_unknown_service_is_reported(system):
    run, processes, _ = system
    assert "start: 'nope' - No such service" in run("nope")
    assert processes.list_processes() == []


def test_service_is_required_without_list(system):
    run, processes, _ = system
    assert "Required argument 'service' is missing" in run()
    assert processes.list_processes() == []


def test_start_works_without_a_port_table():
    buffer = ScreenBuffer(80, 5)
    processes = ProcessTable()
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer, process_table=processes)
    start(ctx, ["netd"])
    assert processes.get_process_by_name("netd") is not None


# --- listing services ---

@pytest.mark.parametrize("flag", ["-l", "--list"])
def test_list_shows_every_known_service(system, flag):
    run, _, _ = system
    out = run(flag)
    assert "Known services:" in out
    for spec in _SYSTEM_PROCESSES:
        assert spec.name in out and spec.description in out


def test_list_shows_which_services_are_running(system):
    run, processes, ports = system
    start_service(find_service("netd"), processes, ports)
    lines = run("-l").splitlines()

    def status(name):
        return next(line for line in lines if line.startswith(f"{name} ")).rstrip().split("|")[-1].strip()

    assert status("netd") == "RUN"
    assert status("syslogd") == "STOP"


def test_list_does_not_start_anything(system):
    run, processes, _ = system
    run("-l")
    assert processes.list_processes() == []
