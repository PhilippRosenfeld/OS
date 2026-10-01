import random
from unittest.mock import patch

import pyglet

from horus.display.screen_buffer import ScreenBuffer
from horus.display.status_bar import StatusBar
from horus.events.bus import EventBus
from horus.events.system_log import LogSeverity, SystemLog
from horus.events.types import MemoryCheckedEvent, MemoryErrorEvent, ProcessKilledEvent
from horus.filesystem.backend.memory import InMemoryVFS
from horus.hardware.cpu import Cpu
from horus.hardware.motherboard import CpuSocket, RamSlots
from horus.hardware.ram import RAM_OVERCLOCK_MAX, Ram
from horus.hardware.spec import HardwareSpec
from horus.kernel.commands.cmd_mem import free, memdump, stress
from horus.processes.memory import DISABLED, MemoryManager, process_memory
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable
from horus.processes.scheduler import CpuScheduler
from horus.processes.system_reactions import register_memory_reactions, register_status_bar, register_system_log
from horus.session.context import Context
from horus.session.user import UserRole
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.ram_screen import ModuleView, RamScreen
from horus.ui.screens.settings_screen import SettingOption

key = pyglet.window.key
PAGE = 256


def make_ram(size=4096, **kwargs):
    return Ram("Test DDR", size, "Test Inc.", power_usage_watts_min=2, power_usage_watts_max=10, **kwargs)


def make_system(modules=(4096, 4096), swap_kb=4096, procs=(), seed=1, fs=None, events=None):
    """Two 4 MB modules (16 pages each) and 4 MB of swap by default."""
    hardware = HardwareSpec()
    hardware.motherboard.ram_slots = [RamSlots(f"DIMM {chr(65 + i)}", [make_ram(size)]) for i, size in enumerate(modules)]
    table = ProcessTable(events=events, total_memory_kb=hardware.total_memory_kb(), total_cpu_mhz=hardware.total_cpu_mhz())
    memory = MemoryManager(table, hardware, events=events, fs=fs, swap_kb=swap_kb, rng=random.Random(seed))
    for name, mem_kb in procs:   # added once the manager runs, like any process started during play
        table.add_process(Process(name=name, pid=0, mem_kb=mem_kb, cpu_mhz=10))
    return hardware, table, memory


def by_name(table, name):
    return next(proc for proc in table.list_processes() if proc.name == name)


def row_text(buffer, row):
    return "".join(buffer.get_cell(c, row).char for c in range(buffer.cols))


def full_text(buffer):
    return "".join(row_text(buffer, r) for r in range(buffer.rows))


# --- Ram module ---

def test_ram_speed_and_instability_follow_clock_and_timings():
    ram = make_ram()
    assert ram.speed_factor == 1.0 and ram.instability == 0.0
    ram.set_overclock(1.2)
    assert ram.speed_factor > 1.0 and ram.instability > 0.0
    stable = ram.instability
    ram.timings = "Extreme"
    assert ram.instability > stable
    ram.timings = "Relaxed"
    assert ram.instability < stable


def test_ram_overclock_is_clamped():
    ram = make_ram()
    ram.set_overclock(9)
    assert ram.overclock == RAM_OVERCLOCK_MAX
    ram.set_overclock(0)
    assert ram.overclock == 1.0


def test_ram_power_grows_with_overclock_and_a_disabled_module_draws_nothing():
    ram = make_ram()
    ram.load = 1.0
    assert ram.calc_current_power_usage() == 10
    ram.set_overclock(1.2)
    assert ram.calc_current_power_usage() == round(10 * 1.2 ** 2)
    ram.enabled = False
    assert ram.calc_current_power_usage() == 0


def test_ram_settings_survive_a_round_trip_and_old_saves_still_load():
    ram = make_ram(enabled=False, overclock=1.3, timings="Tight")
    loaded = Ram.from_dict(ram.to_dict())
    assert (loaded.enabled, loaded.overclock, loaded.timings) == (False, 1.3, "Tight")
    old = {k: v for k, v in ram.to_dict().items() if k not in ("enabled", "overclock", "timings")}
    assert Ram.from_dict(old).enabled is True


def test_total_memory_counts_only_enabled_modules():
    hardware, _, _ = make_system()
    hardware.installed_ram()[1].enabled = False
    assert hardware.total_memory_kb() == 4096


# --- pages, swap, OOM ---

def test_processes_get_contiguous_pages_in_pid_order():
    _, table, memory = make_system(procs=[("a", 3 * PAGE), ("b", 2 * PAGE)])
    memory.tick(0.5)
    a, b = by_name(table, "a"), by_name(table, "b")
    assert memory.pages[:5] == [a.pid] * 3 + [b.pid] * 2
    assert memory.used_kb == 5 * PAGE and a.swapped_kb == b.swapped_kb == 0


def test_a_growing_process_continues_its_block_when_it_can_and_fragments_when_it_cannot():
    _, table, memory = make_system(procs=[("a", PAGE), ("b", PAGE)])
    memory.tick(0.5)
    a = by_name(table, "a")
    a.mem_kb = 3 * PAGE
    memory.tick(0.5)
    owned = [i for i, owner in enumerate(memory.pages) if owner == a.pid]
    assert owned[0] == 0 and owned[1:] == [2, 3]   # b sits right behind a's first page


def test_what_does_not_fit_in_ram_goes_to_swap_newest_process_first():
    _, table, memory = make_system(procs=[("old", 6000), ("new", 4000)])   # 10000 KB > 8192 KB of RAM
    memory.tick(0.5)
    old, new = by_name(table, "old"), by_name(table, "new")
    assert old.swapped_kb == 0
    assert new.swapped_kb > 0
    assert memory.swap_used_kb == new.swapped_kb
    assert 0.0 < new.resident_share < 1.0


def test_the_table_no_longer_shrinks_processes_to_fit_ram():
    _, table, memory = make_system(procs=[("big", 11000)])   # > 8192 KB RAM, fits with swap
    memory.tick(0.5)
    big = by_name(table, "big")
    assert big.mem_kb == 11000
    assert big.swapped_kb == 11000 - 8192


def test_oom_killer_kills_the_biggest_process_and_lets_the_others_back_into_ram():
    bus = EventBus()
    events = []
    bus.subscribe(MemoryErrorEvent, events.append)
    _, table, memory = make_system(procs=[("small", 2048), ("hog", 9000), ("mid", 3000)], events=bus)
    memory.tick(0.5)                                  # 14048 KB > 8192 RAM + 4096 swap
    names = {proc.name for proc in table.list_processes()}
    assert names == {"small", "mid"}                  # only the hog had to go
    assert memory.oom_kills == 1
    assert events[-1].kind == "oom" and "hog" in events[-1].detail
    assert memory.swap_used_kb == 0


def test_oom_killing_init_crashes_the_system():
    bus = EventBus()
    killed = []
    bus.subscribe(ProcessKilledEvent, killed.append)
    hardware, table, memory = make_system(events=bus)
    table.add_process(Process(name="init", pid=0, mem_kb=20000, critical=True))
    memory.tick(0.5)
    assert killed[-1].critical and killed[-1].killed_by == "oom-killer"


def test_disabling_a_module_moves_its_processes_to_swap():
    hardware, table, memory = make_system(procs=[("a", 4096), ("b", 4096)])
    memory.tick(0.5)
    assert memory.module_set_enabled(1, False)
    assert memory.total_kb == 4096
    assert by_name(table, "b").swapped_kb == 4096
    assert DISABLED in memory.page_map()


def test_the_last_enabled_module_cannot_be_disabled():
    _, _, memory = make_system()
    assert memory.module_set_enabled(0, False)
    assert not memory.module_set_enabled(1, False)


def test_paging_loads_the_system_drive_and_module_loads_follow_their_fill():
    hardware, table, memory = make_system(procs=[("a", 4096)])
    memory.tick(0.5)
    assert hardware.installed_ram()[0].load == 1.0 and hardware.installed_ram()[1].load == 0.0
    table.add_process(Process(name="b", pid=0, mem_kb=7000, cpu_mhz=0))   # idle -- no ongoing paging
    memory.tick(0.5)
    burst = hardware.swap_activity
    assert burst > 0.0
    memory.tick(0.5)
    assert 0.0 < hardware.swap_activity < burst       # nothing moved this time -- the burst fades out
    for _ in range(20):
        memory.tick(0.5)
    assert hardware.swap_activity < 0.01


def test_a_busy_swapped_process_keeps_the_system_drive_paging():
    hardware, table, memory = make_system()
    table.add_process(Process(name="filler", pid=0, mem_kb=8192, cpu_mhz=0))
    busy = table.add_process(Process(name="busy", pid=0, mem_kb=4096, cpu_mhz=500))
    for _ in range(20):
        memory.tick(0.5)
    assert busy.swapped_kb == 4096
    assert hardware.swap_activity > 0.1               # thrashing doesn't fade while it keeps running
    busy.cpu_mhz = 0
    for _ in range(20):
        memory.tick(0.5)
    assert hardware.swap_activity < 0.01


def test_swap_activity_shows_up_as_load_on_the_system_drive():
    hardware, table, memory = make_system()
    hardware.swap_activity = 1.0
    hardware._process_table = table
    hardware._sync_component_load_from_process_table()
    system, *others = [hardware.system_drive()] + [d for d in hardware.installed_storage() if d is not hardware.system_drive()]
    assert system.write_load == 1.0
    assert all(drive.write_load < 1.0 for drive in others)


def test_history_and_events_record_memory_state():
    bus = EventBus()
    checked = []
    bus.subscribe(MemoryCheckedEvent, checked.append)
    _, _, memory = make_system(procs=[("a", 4096)], events=bus)
    memory.tick(0.0)
    assert len(memory.history) == 0                   # an immediate re-sync isn't a sample
    memory.tick(0.5)
    assert memory.history.latest() == 50.0
    assert checked[-1].used_kb == 4096 and checked[-1].swap_total_kb == 4096


# --- scheduler integration ---

def test_swapped_processes_get_less_cpu_time_and_faster_memory_more():
    hardware = HardwareSpec()
    hardware.motherboard.cpu_sockets = [CpuSocket("S", [Cpu("C", cores=2, mhz=1000, power_usage_watts_max=50,
                                                                power_usage_watts_min=10, manufacturer="T")])]
    table = ProcessTable(total_memory_kb=hardware.total_memory_kb(), total_cpu_mhz=hardware.total_cpu_mhz())
    resident = table.add_process(Process(name="resident", pid=0, cpu_mhz=500))
    swapped = table.add_process(Process(name="swapped", pid=0, cpu_mhz=500, mem_kb=1000, swapped_kb=500))
    scheduler = CpuScheduler(table, hardware, rng=random.Random(1))
    scheduler.tick(0.0)
    scheduler.tick(1.0)
    assert swapped.cpu_time < resident.cpu_time
    before = resident.cpu_time
    for ram in hardware.installed_ram():
        ram.set_overclock(1.4)
    scheduler.tick(1.0)
    assert resident.cpu_time - before > 0.5


# --- memory errors ---

def test_no_memory_errors_at_stock_settings_and_normal_temperature():
    hardware, _, memory = make_system()
    assert memory.error_chance_per_second() == 0.0


def test_error_chance_rises_with_overclock_timings_and_heat():
    hardware, _, memory = make_system()
    for ram in hardware.installed_ram():
        ram.set_overclock(1.2)
    overclocked = memory.error_chance_per_second()
    for ram in hardware.installed_ram():
        ram.timings = "Extreme"
    assert memory.error_chance_per_second() > overclocked > 0
    cool, _, cool_memory = make_system()
    cool.temperature_celsius = (cool.warning_temperature + cool.critical_temperature) / 2
    assert cool_memory.error_chance_per_second() > 0


def test_a_corrected_error_is_only_reported():
    bus = EventBus()
    events = []
    bus.subscribe(MemoryErrorEvent, events.append)
    _, table, memory = make_system(procs=[("a", 1024)], events=bus)
    memory.tick(0.5)
    memory.trigger_error("corrected")
    assert events[-1].kind == "corrected" and memory.error_count == 1
    assert len(table.list_processes()) == 1


def test_a_crash_error_kills_a_process_holding_ram():
    bus = EventBus()
    killed = []
    bus.subscribe(ProcessKilledEvent, killed.append)
    _, table, memory = make_system(procs=[("victim", 1024)], events=bus)
    memory.tick(0.5)
    memory.trigger_error("crash")
    assert table.list_processes() == []
    assert killed[-1].killed_by == "memory-error"


def test_a_corruption_error_flips_characters_in_a_file():
    fs = InMemoryVFS()
    fs.write_file("/notes.txt", "a" * 200, user="root")
    bus = EventBus()
    events = []
    bus.subscribe(MemoryErrorEvent, events.append)
    _, _, memory = make_system(fs=fs, events=bus)
    memory.trigger_error("corruption")
    assert fs.read_file("/notes.txt", user="root") != "a" * 200
    assert events[-1].kind == "corruption" and "/notes.txt" in events[-1].detail


def test_corruption_without_a_usable_file_falls_back_to_a_corrected_error():
    bus = EventBus()
    events = []
    bus.subscribe(MemoryErrorEvent, events.append)
    _, _, memory = make_system(fs=InMemoryVFS(), events=bus)
    memory.trigger_error("corruption")
    assert events[-1].kind == "corrected"


# --- reactions ---

def test_memory_errors_land_in_the_system_log_and_play_sounds():
    bus = EventBus()
    log = SystemLog()
    register_system_log(bus, log)
    played = []

    class Sounds:
        def play(self, name):
            played.append(name)

    register_memory_reactions(bus, Sounds())
    bus.publish(MemoryErrorEvent(kind="corrected", detail="fixed"))
    bus.publish(MemoryErrorEvent(kind="oom", detail="killed x"))
    assert [(e.severity, e.message) for e in log.entries()] == [(LogSeverity.WARNING, "fixed"), (LogSeverity.ERROR, "killed x")]
    assert played == ["error_notification", "system_error_notification"]


def test_msc_light_is_on_while_swapping():
    bus = EventBus()
    bar = StatusBar(40)
    register_status_bar(bus, bar)
    bus.publish(MemoryCheckedEvent(used_kb=1, total_kb=2, swap_used_kb=5, swap_total_kb=10))
    assert bar._lit["MSC"] is True
    bus.publish(MemoryCheckedEvent(used_kb=1, total_kb=2, swap_used_kb=0, swap_total_kb=10))
    assert bar._lit["MSC"] is False


# --- memory contents ---

def test_process_memory_is_deterministic_and_contains_its_strings():
    proc = Process(name="vault", pid=7, owner="root", mem_kb=64, memory_strings=["KEY=hunter2"])
    dump = process_memory(proc, 0, 4096)
    assert dump == process_memory(proc, 0, 4096)
    assert b"vault" in dump and b"KEY=hunter2" in dump
    assert process_memory(proc, 64 * 1024, 16) == b""     # past the end


# --- commands ---

def make_ctx(user="root", role=UserRole.ROOT, memory=True):
    buffer = ScreenBuffer(100, 120)
    hardware, table, manager = make_system(procs=[("secretd", 1024)])
    by_name(table, "secretd").memory_strings = ["PASSWORD=swordfish"]
    manager.tick(0.5)
    ctx = Context(session_id="s", user=user, cwd="/", screen=buffer, process_table=table, hardware=hardware,
                  memory_manager=manager if memory else None)
    ctx.effective_role_override = role
    return ctx, buffer, table, manager


def test_free_shows_ram_and_swap():
    ctx, buffer, table, manager = make_ctx()
    free(ctx, [])
    text = full_text(buffer)
    assert "Mem:" in text and "Swap:" in text
    assert f"{manager.total_kb}" in text


def test_memdump_shows_hex_and_the_strings_in_the_processes_memory():
    ctx, buffer, table, _ = make_ctx()
    pid = by_name(table, "secretd").pid
    memdump(ctx, [str(pid), "-n", "64"])
    text = full_text(buffer)
    assert "secretd (PID" in text
    assert "00000000  " in text
    assert "PASSWORD" in text


def test_memdump_refuses_someone_elses_process_for_a_plain_user():
    ctx, buffer, table, _ = make_ctx(user="guest")
    pid = by_name(table, "secretd").pid
    with patch.object(Context, "effective_role", UserRole.USER):
        memdump(ctx, [str(pid)])
    assert "Operation not permitted" in full_text(buffer)


def test_memdump_rejects_an_offset_past_the_end():
    ctx, buffer, table, _ = make_ctx()
    pid = by_name(table, "secretd").pid
    memdump(ctx, [str(pid), "-o", "0x10000000"])
    assert "past the end" in full_text(buffer)


def test_stress_starts_a_killable_process():
    ctx, buffer, table, _ = make_ctx()
    stress(ctx, ["-c", "300", "-m", "8192", "--name", "hog"])
    hog = by_name(table, "hog")
    assert (hog.cpu_mhz, hog.mem_kb, hog.killable) == (300, 8192, True)
    assert f"kill {hog.pid}" in full_text(buffer)


# --- RamScreen ---

def make_screen(page_map, names, modules=None, options=None):
    buffer = ScreenBuffer(80, 24)
    manager = ScreenManager()
    toggled = []
    modules = modules or [ModuleView("DIMM A", 4096, True, 50.0), ModuleView("DIMM B", 4096, False, 0.0)]
    screen = RamScreen(buffer, manager, "RAM", info_fn=lambda: ["Used: x"], history_fn=lambda: [10.0, 20.0],
                       map_fn=lambda: page_map, names_fn=lambda: names, modules_fn=lambda: modules,
                       on_toggle_module=toggled.append, options=options)
    with patch("pyglet.clock.schedule_interval"):
        manager.push(screen)
    return screen, buffer, manager, toggled


def test_ram_screen_draws_the_memory_map_with_a_legend():
    page_map = [1, 1, 2, None, None, DISABLED]
    screen, buffer, *_ = make_screen(page_map, {1: "init", 2: "bash"})
    text = full_text(buffer)
    assert "AAB..x" in text
    assert "A init" in text and "B bash" in text
    assert "Memory Map" in text and "Memory Usage" in text


def test_ram_screen_shows_modules_with_sprites_and_toggles():
    screen, buffer, *_ = make_screen([None], {})
    text = full_text(buffer)
    assert "DIMM A  < Enabled >" in text and "DIMM B  < Disabled >" in text
    assert "50% used" in text
    assert list(buffer.sprites.values()) == ["ram", "ram"]


def test_ram_screen_toggles_modules_and_steps_options():
    value = {"clock": 100}
    options = [SettingOption("Clock", get_value=lambda: f"{value['clock']}%",
                             on_left=lambda: value.update(clock=value["clock"] - 10),
                             on_right=lambda: value.update(clock=value["clock"] + 10))]
    screen, buffer, manager, toggled = make_screen([None], {}, options=options)
    screen.handle_enter()
    screen.handle_motion(key.MOTION_DOWN)
    screen.handle_motion(key.MOTION_RIGHT)
    assert toggled == [0, 1]
    screen.handle_motion(key.MOTION_DOWN)
    screen.handle_motion(key.MOTION_RIGHT)
    assert value["clock"] == 110
    assert "Clock: < 110% >" in full_text(buffer)
    with patch("pyglet.clock.unschedule"):
        screen.handle_key(key.ESCAPE, 0)
    assert manager.active is None


def test_ram_screen_lists_processes_that_live_in_swap():
    buffer = ScreenBuffer(80, 24)
    manager = ScreenManager()
    screen = RamScreen(buffer, manager, "RAM", info_fn=lambda: [], history_fn=lambda: [],
                       map_fn=lambda: [1, None], names_fn=lambda: {1: "init"},
                       modules_fn=lambda: [], on_toggle_module=lambda i: None,
                       swapped_fn=lambda: [("hog", 9000)])
    with patch("pyglet.clock.schedule_interval"):
        manager.push(screen)
    assert "In swap: hog 9000 KB" in full_text(buffer)


def test_ram_screen_legend_wraps_instead_of_dropping_processes():
    names = {pid: f"process{pid}" for pid in range(1, 9)}
    screen, buffer, *_ = make_screen(list(range(1, 9)) + [None], names)
    text = full_text(buffer)
    assert all(f"{letter} process{pid}" in text for pid, letter in zip(range(1, 9), "ABCDEFGH"))
    assert ". free" in text and "x off" in text
