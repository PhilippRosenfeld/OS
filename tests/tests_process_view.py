from datetime import datetime, timedelta

from horus.processes.process import process as Process
from horus.processes.process_view import format_uptime, sort_processes


def make(name, **kwargs):
    return Process(name=name, pid=kwargs.pop("pid", 0), **kwargs)


# --- sort_processes ---

def test_sort_by_cpu_is_descending():
    procs = [make("a", cpu_percent=10.0), make("b", cpu_percent=90.0), make("c", cpu_percent=50.0)]
    result = sort_processes(procs, "cpu")
    assert [p.name for p in result] == ["b", "c", "a"]


def test_sort_by_mem_is_descending():
    procs = [make("a", mem_kb=100), make("b", mem_kb=900), make("c", mem_kb=500)]
    result = sort_processes(procs, "mem")
    assert [p.name for p in result] == ["b", "c", "a"]


def test_sort_by_pid_is_ascending():
    procs = [make("a", pid=3), make("b", pid=1), make("c", pid=2)]
    result = sort_processes(procs, "pid")
    assert [p.name for p in result] == ["b", "c", "a"]


def test_sort_by_name_is_alphabetical_and_case_insensitive():
    procs = [make("Charlie"), make("alpha"), make("Bravo")]
    result = sort_processes(procs, "name")
    assert [p.name for p in result] == ["alpha", "Bravo", "Charlie"]


def test_sort_by_time_puts_the_longest_running_first():
    now = datetime.now()
    procs = [
        make("young", started_at=now - timedelta(seconds=5)),
        make("old", started_at=now - timedelta(hours=1)),
        make("middle", started_at=now - timedelta(minutes=10)),
    ]
    result = sort_processes(procs, "time")
    assert [p.name for p in result] == ["old", "middle", "young"]


def test_sort_processes_default_is_cpu():
    procs = [make("a", cpu_percent=10.0), make("b", cpu_percent=90.0)]
    assert sort_processes(procs) == sort_processes(procs, "cpu")


def test_sort_processes_does_not_mutate_the_input_list():
    procs = [make("a", cpu_percent=10.0), make("b", cpu_percent=90.0)]
    original_order = list(procs)
    sort_processes(procs, "cpu")
    assert procs == original_order


def test_sort_processes_with_an_unknown_key_falls_back_to_cpu():
    procs = [make("a", cpu_percent=10.0), make("b", cpu_percent=90.0)]
    assert sort_processes(procs, "not-a-real-column") == sort_processes(procs, "cpu")


# --- format_uptime ---

def test_format_uptime_under_a_minute():
    now = datetime(2026, 1, 1, 12, 0, 30)
    started = datetime(2026, 1, 1, 12, 0, 0)
    assert format_uptime(started, now) == "00:30"


def test_format_uptime_several_minutes():
    now = datetime(2026, 1, 1, 12, 5, 42)
    started = datetime(2026, 1, 1, 12, 0, 0)
    assert format_uptime(started, now) == "05:42"


def test_format_uptime_switches_to_hours_format():
    now = datetime(2026, 1, 1, 13, 30, 15)
    started = datetime(2026, 1, 1, 12, 0, 0)
    assert format_uptime(started, now) == "1:30:15"


def test_format_uptime_zero_when_just_started():
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert format_uptime(now, now) == "00:00"


def test_format_uptime_defaults_now_to_the_current_time():
    started = datetime.now() - timedelta(seconds=3)
    result = format_uptime(started)  # now= omitted
    assert result in ("00:03", "00:04")  # tolerate a little test-execution drift
