from unittest.mock import patch

import pytest

from horus.events.bus import EventBus
from horus.events.types import ProcessKilledEvent, ProcessStartedEvent
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable
from horus.session.user import UserRole

# --- ProcessTable: add/remove/list/get ---

def test_add_process_assigns_an_incrementing_pid():
    table = ProcessTable()
    first = table.add_process(Process(name="a", pid=0))
    second = table.add_process(Process(name="b", pid=0))
    assert first.pid == 1
    assert second.pid == 2


def test_add_process_with_none_raises():
    table = ProcessTable()
    with pytest.raises(ValueError):
        table.add_process(None)


def test_list_processes_returns_everything_added():
    table = ProcessTable()
    table.add_process(Process(name="a", pid=0))
    table.add_process(Process(name="b", pid=0))
    assert {p.name for p in table.list_processes()} == {"a", "b"}


def test_get_process_returns_none_for_unknown_pid():
    table = ProcessTable()
    assert table.get_process(999) is None


def test_remove_process_by_owner_succeeds():
    table = ProcessTable()
    proc = table.add_process(Process(name="a", pid=0, owner="user1"))
    assert table.remove_process(proc.pid, user="user1") is True
    assert table.get_process(proc.pid) is None


def test_remove_process_by_admin_role_succeeds_even_for_someone_elses():
    table = ProcessTable()
    proc = table.add_process(Process(name="a", pid=0, owner="user1"))
    assert table.remove_process(proc.pid, user="admin", role=UserRole.ADMIN) is True


def test_remove_process_by_root_role_succeeds_even_for_someone_elses():
    table = ProcessTable()
    proc = table.add_process(Process(name="a", pid=0, owner="user1"))
    assert table.remove_process(proc.pid, user="root", role=UserRole.ROOT) is True


def test_remove_process_by_a_different_plain_user_fails():
    """A plain USER role -- even literally named 'root' -- can't kill someone
    else's process; only the role matters, not the username."""
    table = ProcessTable()
    proc = table.add_process(Process(name="a", pid=0, owner="user1"))
    assert table.remove_process(proc.pid, user="root", role=UserRole.USER) is False
    assert table.get_process(proc.pid) is not None


def test_remove_process_role_defaults_to_least_privileged():
    """Callers that don't pass a role (e.g. legacy code) fail closed --
    can't kill someone else's process -- rather than silently allowing it."""
    table = ProcessTable()
    proc = table.add_process(Process(name="a", pid=0, owner="user1"))
    assert table.remove_process(proc.pid, user="user2") is False
    assert table.get_process(proc.pid) is not None


def test_remove_unknown_pid_returns_false():
    table = ProcessTable()
    assert table.remove_process(999, user="root", role=UserRole.ROOT) is False


# --- event publishing ---

def test_add_process_publishes_process_started_event():
    bus = EventBus()
    received = []
    bus.subscribe(ProcessStartedEvent, received.append)
    table = ProcessTable(events=bus)

    proc = table.add_process(Process(name="a", pid=0, owner="user1"))

    assert len(received) == 1
    assert received[0].pid == proc.pid
    assert received[0].name == "a"
    assert received[0].owner == "user1"


def test_remove_process_publishes_process_killed_event():
    bus = EventBus()
    received = []
    bus.subscribe(ProcessKilledEvent, received.append)
    table = ProcessTable(events=bus)
    proc = table.add_process(Process(name="a", pid=0, owner="user1"))

    table.remove_process(proc.pid, user="root", role=UserRole.ROOT)

    assert len(received) == 1
    assert received[0].pid == proc.pid
    assert received[0].name == "a"
    assert received[0].killed_by == "root"


def test_remove_process_denied_does_not_publish_an_event():
    bus = EventBus()
    received = []
    bus.subscribe(ProcessKilledEvent, received.append)
    table = ProcessTable(events=bus)
    proc = table.add_process(Process(name="a", pid=0, owner="user1"))

    assert table.remove_process(proc.pid, user="user2") is False  # not the owner, not admin/root
    assert received == []


def test_without_an_event_bus_add_and_remove_do_not_raise():
    table = ProcessTable()  # events=None, the default
    proc = table.add_process(Process(name="a", pid=0, owner="user1"))
    assert table.remove_process(proc.pid, user="user1") is True


# --- fluctuation ---

def test_start_fluctuating_schedules_via_pyglet_clock():
    table = ProcessTable(fluctuation_interval=2.0)
    with patch("pyglet.clock.schedule_interval") as mock_schedule:
        table.start_fluctuating()
    mock_schedule.assert_called_once()
    callback, interval = mock_schedule.call_args[0]
    assert interval == 2.0
    assert callback == table._fluctuate


def test_stop_fluctuating_unschedules_the_tick():
    table = ProcessTable()
    with patch("pyglet.clock.unschedule") as mock_unschedule:
        table.stop_fluctuating()
    mock_unschedule.assert_called_once_with(table._fluctuate)


def test_fluctuate_changes_cpu_and_mem_of_every_process():
    """Each process makes two random.uniform() calls per tick, in order:
    cpu delta, then mem delta."""
    table = ProcessTable()
    p1 = table.add_process(Process(name="a", pid=0, cpu_mhz=10.0, mem_kb=1000))
    p2 = table.add_process(Process(name="b", pid=0, cpu_mhz=20.0, mem_kb=2000))

    with patch("random.uniform", side_effect=[1.5, 48.0, -1.5, -48.0]):
        table._fluctuate(0.0)

    assert p1.cpu_mhz == pytest.approx(11.5)
    assert p1.mem_kb == 1048
    assert p2.cpu_mhz == pytest.approx(18.5)
    assert p2.mem_kb == 1952


def test_fluctuate_clamps_cpu_mhz_to_the_table_s_total_capacity():
    table = ProcessTable(total_cpu_mhz=100)
    high = table.add_process(Process(name="hot", pid=0, cpu_mhz=99.5))

    with patch("random.uniform", return_value=10.0):
        table._fluctuate(0.0)
    assert high.cpu_mhz == pytest.approx(100.0)


def test_fluctuate_clamps_cpu_mhz_to_the_lower_bound():
    table = ProcessTable()
    low = table.add_process(Process(name="idle", pid=0, cpu_mhz=0.2))

    with patch("random.uniform", return_value=-10.0):
        table._fluctuate(0.0)
    assert low.cpu_mhz == pytest.approx(0.0)


def test_fluctuate_never_drops_memory_below_the_floor():
    table = ProcessTable()
    tiny = table.add_process(Process(name="tiny", pid=0, mem_kb=100))

    with patch("random.uniform", return_value=-1000.0):
        table._fluctuate(0.0)

    assert tiny.mem_kb == 128  # clamped to the floor, not negative


# --- per-process volatility ---

def test_fluctuate_scales_cpu_step_by_volatility():
    table = ProcessTable()
    table.add_process(Process(name="calm", pid=0, cpu_mhz=10.0, volatility=0.2))
    table.add_process(Process(name="jumpy", pid=0, cpu_mhz=10.0, volatility=2.0))

    captured_ranges = []
    def fake_uniform(low, high):
        captured_ranges.append(high)
        return 0.0
    with patch("random.uniform", side_effect=fake_uniform):
        table._fluctuate(0.0)

    cpu_range_calm, mem_range_calm, cpu_range_jumpy, mem_range_jumpy = captured_ranges
    assert cpu_range_calm == pytest.approx(40 * 0.2)
    assert cpu_range_jumpy == pytest.approx(40 * 2.0)
    assert cpu_range_jumpy > cpu_range_calm


def test_fluctuate_scales_mem_step_by_volatility():
    table = ProcessTable()
    table.add_process(Process(name="calm", pid=0, mem_kb=1000, volatility=0.5))
    table.add_process(Process(name="jumpy", pid=0, mem_kb=1000, volatility=3.0))

    captured_ranges = []
    def fake_uniform(low, high):
        captured_ranges.append(high)
        return 0.0
    with patch("random.uniform", side_effect=fake_uniform):
        table._fluctuate(0.0)

    # calls per process are (cpu, mem) in order -- index 1 and 3 are the mem ranges
    mem_range_calm, mem_range_jumpy = captured_ranges[1], captured_ranges[3]
    assert mem_range_calm == pytest.approx(48 * 0.5)
    assert mem_range_jumpy == pytest.approx(48 * 3.0)
    assert mem_range_jumpy > mem_range_calm


def test_zero_volatility_never_moves_the_process():
    """volatility=0.0 collapses the random range to (0, 0), so even without
    mocking random at all, real random.uniform(0, 0) always returns 0."""
    table = ProcessTable()
    frozen = table.add_process(Process(name="frozen", pid=0, cpu_mhz=42.0, mem_kb=2048, volatility=0.0))

    for _ in range(20):  # run several real (unmocked) ticks, not just one
        table._fluctuate(0.0)

    assert frozen.cpu_mhz == pytest.approx(42.0)
    assert frozen.mem_kb == 2048


# --- adjust_load (hook for future event-driven load changes) ---

def test_adjust_load_raises_cpu_and_mem():
    table = ProcessTable()
    proc = table.add_process(Process(name="a", pid=0, cpu_mhz=10.0, mem_kb=1000))
    table.adjust_load(proc.pid, cpu_delta=15.0, mem_delta=200)
    assert proc.cpu_mhz == pytest.approx(25.0)
    assert proc.mem_kb == 1200


def test_adjust_load_can_lower_cpu_and_mem():
    table = ProcessTable()
    proc = table.add_process(Process(name="a", pid=0, cpu_mhz=50.0, mem_kb=2000))
    table.adjust_load(proc.pid, cpu_delta=-20.0, mem_delta=-500)
    assert proc.cpu_mhz == pytest.approx(30.0)
    assert proc.mem_kb == 1500


def test_adjust_load_clamps_like_organic_fluctuation():
    table = ProcessTable(total_cpu_mhz=100)
    proc = table.add_process(Process(name="a", pid=0, cpu_mhz=90.0, mem_kb=200))
    table.adjust_load(proc.pid, cpu_delta=50.0, mem_delta=-1000)
    assert proc.cpu_mhz == pytest.approx(100.0)
    assert proc.mem_kb == 128


def test_adjust_load_on_unknown_pid_is_a_noop():
    table = ProcessTable()
    table.adjust_load(999, cpu_delta=10.0, mem_delta=100)  # should not raise


# --- combined resource totals / caps ---

def test_used_cpu_mhz_sums_every_process():
    table = ProcessTable()
    table.add_process(Process(name="a", pid=0, cpu_mhz=10.0))
    table.add_process(Process(name="b", pid=0, cpu_mhz=25.0))
    assert table.used_cpu_mhz() == pytest.approx(35.0)


def test_used_mem_kb_sums_every_process():
    table = ProcessTable()
    table.add_process(Process(name="a", pid=0, mem_kb=1000))
    table.add_process(Process(name="b", pid=0, mem_kb=2000))
    assert table.used_mem_kb() == 3000


def test_total_memory_kb_defaults_to_8_gib():
    table = ProcessTable()
    assert table.total_memory_kb == 8 * 1024 * 1024


def test_total_memory_kb_is_configurable():
    table = ProcessTable(total_memory_kb=4096)
    assert table.total_memory_kb == 4096


def test_total_cpu_mhz_defaults_to_3200():
    """Matches HardwareSpec's own default (cpu_mhz=3200, cpu_cores=1)."""
    table = ProcessTable()
    assert table.total_cpu_mhz == 3200


def test_total_cpu_mhz_is_configurable():
    table = ProcessTable(total_cpu_mhz=6400)
    assert table.total_cpu_mhz == 6400


def test_add_process_scales_cpu_down_when_it_would_exceed_the_cap():
    table = ProcessTable(total_cpu_mhz=100)
    table.add_process(Process(name="a", pid=0, cpu_mhz=60.0))
    table.add_process(Process(name="b", pid=0, cpu_mhz=60.0))  # 120 combined -- over the 100 cap

    assert table.used_cpu_mhz() == pytest.approx(100.0)


def test_add_process_scaling_preserves_relative_cpu_shares():
    table = ProcessTable(total_cpu_mhz=100)
    a = table.add_process(Process(name="a", pid=0, cpu_mhz=30.0))
    b = table.add_process(Process(name="b", pid=0, cpu_mhz=90.0))  # 3x a, combined 120

    assert b.cpu_mhz == pytest.approx(a.cpu_mhz * 3)
    assert table.used_cpu_mhz() == pytest.approx(100.0)


def test_add_process_scales_mem_down_when_it_would_exceed_the_cap():
    table = ProcessTable(total_memory_kb=1000)
    table.add_process(Process(name="a", pid=0, mem_kb=800))
    table.add_process(Process(name="b", pid=0, mem_kb=800))  # 1600 combined -- over the 1000 cap

    assert table.used_mem_kb() == 1000


def test_add_process_under_budget_does_not_scale_anything():
    table = ProcessTable()
    a = table.add_process(Process(name="a", pid=0, cpu_mhz=10.0, mem_kb=1000))
    assert a.cpu_mhz == pytest.approx(10.0)
    assert a.mem_kb == 1000


def test_fluctuate_keeps_total_cpu_within_budget_even_after_many_ticks():
    table = ProcessTable(total_cpu_mhz=100)
    for i in range(10):
        table.add_process(Process(name=f"p{i}", pid=0, cpu_mhz=5.0, volatility=5.0))

    with patch("random.uniform", return_value=50.0):  # every process wants to spike hard
        table._fluctuate(0.0)

    assert table.used_cpu_mhz() <= 100.0 + 1e-6


def test_adjust_load_keeps_total_cpu_within_budget():
    table = ProcessTable(total_cpu_mhz=100)
    a = table.add_process(Process(name="a", pid=0, cpu_mhz=50.0))
    table.add_process(Process(name="b", pid=0, cpu_mhz=50.0))

    table.adjust_load(a.pid, cpu_delta=50.0)  # would push the total to 150

    assert table.used_cpu_mhz() == pytest.approx(100.0)


def test_removing_a_process_never_needs_to_scale_anything_up():
    """Removal only frees up budget -- the remaining processes keep their
    exact values rather than being scaled back up to fill the gap."""
    table = ProcessTable()
    a = table.add_process(Process(name="a", pid=0, cpu_mhz=40.0))
    b = table.add_process(Process(name="b", pid=0, cpu_mhz=40.0))

    table.remove_process(b.pid, user="root", role=UserRole.ROOT)

    assert a.cpu_mhz == pytest.approx(40.0)
