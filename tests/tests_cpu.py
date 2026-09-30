import random
from unittest.mock import patch

import numpy as np
import pyglet
from PIL import Image

from horus.display.screen_buffer import ScreenBuffer
from horus.display.sprite_atlas import SpriteAtlas
from horus.hardware.cpu import OVERCLOCK_MAX, CoreState, Cpu
from horus.hardware.motherboard import CpuSocket
from horus.hardware.spec import HardwareSpec
from horus.processes.process import process as Process
from horus.processes.process_view import format_core, format_cpu_time
from horus.processes.processTable import ProcessTable
from horus.processes.scheduler import CpuScheduler
from horus.ui.screen_manager import ScreenManager
from horus.ui.screens.cpu_screen import LAMP_COLORS, TIMESCALES, CoreView, CpuScreen
from horus.ui.screens.settings_screen import SettingOption

key = pyglet.window.key


def make_cpu(cores=4, mhz=1000, **kwargs):
    return Cpu("Test CPU", cores=cores, mhz=mhz, power_usage_watts_max=50, power_usage_watts_min=10,
               manufacturer="Test Inc.", **kwargs)


def make_system(cores=4, mhz=1000, procs=(), seed=1):
    hardware = HardwareSpec()
    hardware.motherboard.cpu_sockets = [CpuSocket("Socket", [make_cpu(cores, mhz)])]
    table = ProcessTable(total_memory_kb=1024 * 1024, total_cpu_mhz=hardware.total_cpu_mhz())
    for name, cpu_mhz in procs:
        table.add_process(Process(name=name, pid=0, cpu_mhz=cpu_mhz, mem_kb=1024))
    return hardware, table, CpuScheduler(table, hardware, rng=random.Random(seed))


def row_text(buffer, row):
    return "".join(buffer.get_cell(c, row).char for c in range(buffer.cols))


def full_text(buffer):
    return "".join(row_text(buffer, r) for r in range(buffer.rows))


# --- Cpu / cores ---

def test_cpu_creates_one_core_per_core_count_all_enabled_by_default():
    cpu = make_cpu(cores=3)
    assert [core.index for core in cpu.core_list] == [0, 1, 2]
    assert all(core.state == CoreState.STANDBY for core in cpu.core_list)


def test_core_state_reflects_enabled_and_working():
    core = make_cpu().core_list[0]
    core.working = True
    assert core.state == CoreState.WORKING
    core.enabled = False
    assert core.state == CoreState.DISABLED


def test_overclock_raises_the_clock_and_is_clamped():
    cpu = make_cpu(mhz=1000)
    cpu.set_overclock(1.2)
    assert cpu.effective_mhz == 1200
    cpu.set_overclock(9.0)
    assert cpu.overclock == OVERCLOCK_MAX
    cpu.set_overclock(0.1)
    assert cpu.overclock == 1.0


def test_power_draw_at_stock_is_the_plain_min_max_interpolation():
    cpu = make_cpu(cores=2)            # 10 W idle, 50 W max
    assert cpu.calc_current_power_usage() == 10
    cpu.load = 1.0
    assert cpu.calc_current_power_usage() == 50
    cpu.load = 0.5
    assert cpu.calc_current_power_usage() == 30


def test_each_core_draws_by_its_own_load():
    cpu = make_cpu(cores=2)            # per core: 5 W idle + up to 20 W dynamic
    cpu.core_list[0].load = 1.0
    assert cpu.core_power_usage(cpu.core_list[0]) == 25
    assert cpu.core_power_usage(cpu.core_list[1]) == 5
    assert cpu.calc_current_power_usage() == 30


def test_a_disabled_core_draws_nothing_not_even_idle():
    cpu = make_cpu(cores=2)
    cpu.core_list[1].enabled = False
    assert cpu.calc_current_power_usage() == 5          # only core 0's idle share
    cpu.load = 1.0                                       # spreads over the enabled core only
    assert cpu.calc_current_power_usage() == 25
    assert cpu.core_list[1].load == 0.0


def test_overclock_raises_idle_linearly_and_load_quadratically():
    cpu = make_cpu(cores=2)
    cpu.set_overclock(1.5)
    assert cpu.calc_current_power_usage() == round(10 * 1.5)              # idle: 15 W
    cpu.load = 1.0
    assert cpu.calc_current_power_usage() == round(10 * 1.5 + 40 * 1.5 ** 2)   # 105 W


def test_cpu_load_is_the_average_over_the_enabled_cores():
    cpu = make_cpu(cores=4)
    cpu.core_list[0].load = 1.0
    cpu.core_list[1].load = 0.5
    cpu.core_list[3].enabled = False
    cpu.core_list[3].load = 1.0                          # ignored while disabled
    assert cpu.load == 0.5


def test_disabling_idle_cores_saves_power_for_the_same_work():
    """The point of per-core power: the same processes on fewer cores cost
    less, since switched-off cores stop drawing their idle share."""
    hardware, table, scheduler = make_system(cores=8, mhz=1000, procs=[("a", 400), ("b", 400)])
    scheduler.tick(0.5)
    all_on = hardware.installed_cpus()[0].calc_current_power_usage()
    busy = {proc.core for proc in table.list_processes()}
    for n in range(8):
        if n not in busy:
            scheduler.set_core_enabled(n, False)
    assert hardware.installed_cpus()[0].calc_current_power_usage() < all_on


def test_power_monitoring_keeps_the_schedulers_per_core_loads():
    hardware, table, scheduler = make_system(cores=2, mhz=1000, procs=[("busy", 800)])
    scheduler.tick(0.5)
    busy_core = hardware.installed_cores()[table.list_processes()[0].core][1]
    hardware._process_table = table
    hardware._sync_component_load_from_process_table()
    assert busy_core.load == 0.8        # not flattened to the CPU-wide average of 0.4


def test_disabled_cores_and_overclock_survive_a_save_load_round_trip():
    cpu = make_cpu(cores=4, overclock=1.3, disabled_cores=[1, 3])
    loaded = Cpu.from_dict(cpu.to_dict())
    assert loaded.overclock == 1.3
    assert [core.enabled for core in loaded.core_list] == [True, False, True, False]


def test_cpu_saved_before_cores_existed_still_loads():
    data = make_cpu().to_dict()
    del data["overclock"], data["disabled_cores"]
    assert Cpu.from_dict(data).overclock == 1.0


def test_total_cpu_mhz_counts_only_enabled_cores_at_their_overclocked_clock():
    hardware, _, _ = make_system(cores=4, mhz=1000)
    cpu = hardware.installed_cpus()[0]
    cpu.core_list[0].enabled = False
    cpu.set_overclock(1.5)
    assert hardware.total_cpu_mhz() == 3 * 1500


# --- scheduler ---

def test_every_process_is_pinned_to_exactly_one_enabled_core_spreading_the_load():
    _, table, scheduler = make_system(cores=2, procs=[("a", 300), ("b", 300), ("c", 100)])
    scheduler.tick(0.5)
    cores = [proc.core for proc in table.list_processes()]
    assert all(core in (0, 1) for core in cores)
    assert set(cores) == {0, 1}   # not everything piled onto one core


def test_processes_stay_on_their_core_between_ticks():
    _, table, scheduler = make_system(cores=4, procs=[("a", 100), ("b", 200)])
    scheduler.tick(0.5)
    before = {proc.pid: proc.core for proc in table.list_processes()}
    for _ in range(5):
        scheduler.tick(0.5)
    assert {proc.pid: proc.core for proc in table.list_processes()} == before


def test_disabling_a_core_moves_its_processes_and_shrinks_the_capacity():
    hardware, table, scheduler = make_system(cores=2, mhz=1000, procs=[("a", 100), ("b", 100)])
    scheduler.tick(0.5)
    victim = table.list_processes()[0].core

    assert scheduler.set_core_enabled(victim, False)

    assert all(proc.core != victim for proc in table.list_processes())
    assert table.total_cpu_mhz == 1000
    assert hardware.installed_cores()[victim][1].state == CoreState.DISABLED


def test_the_last_enabled_core_cannot_be_disabled():
    _, _, scheduler = make_system(cores=2)
    assert scheduler.set_core_enabled(0, False)
    assert not scheduler.set_core_enabled(1, False)


def test_overclocking_through_the_scheduler_raises_the_tables_capacity():
    _, table, scheduler = make_system(cores=2, mhz=1000)
    scheduler.set_overclock(1.2)
    assert table.total_cpu_mhz == 2400


def test_a_process_can_never_use_more_than_its_own_core():
    _, table, scheduler = make_system(cores=2, mhz=1000, procs=[("hog", 1800)])
    scheduler.tick(0.5)
    assert table.list_processes()[0].cpu_mhz <= 1000


def test_cpu_time_accumulates_by_the_share_of_its_core_a_process_uses():
    _, table, scheduler = make_system(cores=1, mhz=1000, procs=[("half", 500)])
    scheduler.tick(0.0)
    for _ in range(4):
        scheduler.tick(0.5)
    assert table.list_processes()[0].cpu_time == 1.0   # 2s wall time at 50% of its core


def test_an_idle_core_stays_in_standby_and_a_saturated_one_works_on_its_process():
    hardware, table, scheduler = make_system(cores=2, mhz=1000, procs=[("busy", 1000)])
    scheduler.tick(0.5)
    busy = table.list_processes()[0]
    cores = hardware.installed_cores()
    working = cores[busy.core][1]
    idle = cores[1 - busy.core][1]
    assert working.state == CoreState.WORKING and working.current_pid == busy.pid
    assert idle.state == CoreState.STANDBY and idle.current_pid is None


def test_scheduler_records_each_cores_state_per_tick_but_not_on_resyncs():
    hardware, table, scheduler = make_system(cores=2, mhz=1000, procs=[("busy", 1000)])
    for _ in range(3):
        scheduler.tick(0.5)
    scheduler.set_core_enabled(1, False)   # immediate re-sync (dt=0) -- no extra sample
    scheduler.tick(0.5)

    cores = [core for _, core in hardware.installed_cores()]
    assert all(len(core.history) == 4 for core in cores)
    assert cores[1].history[-1] == CoreState.DISABLED
    busy_core = cores[table.list_processes()[0].core]
    assert busy_core.history[-1] == CoreState.WORKING


# --- top formatting ---

def test_format_cpu_time_like_tops_time_column():
    assert format_cpu_time(0) == "0:00.00"
    assert format_cpu_time(75.456) == "1:15.45"
    assert format_cpu_time(3725) == "1:02:05"


def test_format_core_is_one_based_or_a_dash():
    assert format_core(Process(name="p", pid=1)) == "-"
    assert format_core(Process(name="p", pid=1, core=0)) == "1"


# --- CpuScreen ---

def make_screen(cores, options=None, cols=100, rows=30):
    buffer = ScreenBuffer(cols, rows)
    manager = ScreenManager()
    toggled = []
    state = {"cores": list(cores)}
    screen = CpuScreen(buffer, manager, "CPU", info_fn=lambda: ["Test CPU"], cores_fn=lambda: state["cores"],
                       on_toggle_core=toggled.append, options=options)
    with patch("pyglet.clock.schedule_interval"):
        manager.push(screen)
    return screen, buffer, manager, toggled, state


def _chart_rows(buffer):
    """label -> (lamp color, list of (char, fg) chart cells after the label) for every chart row."""
    rows = {}
    for r in range(buffer.rows):
        for c in range(buffer.cols):
            cell = buffer.get_cell(c, r)
            if cell.char == "■":
                label = row_text(buffer, r)[c + 2:c + 8]
                chart = [(buffer.get_cell(x, r).char, buffer.get_cell(x, r).fg_color) for x in range(c + 9, buffer.cols - 2)]
                rows[label] = (cell.fg_color, chart)
    return rows


def test_cpu_screen_shows_a_colored_lamp_per_core_in_the_chart():
    cores = [CoreView("Core 1", CoreState.WORKING, "bash (2)"), CoreView("Core 2", CoreState.STANDBY),
             CoreView("Core 3", CoreState.DISABLED)]
    screen, buffer, *_ = make_screen(cores)
    rows = _chart_rows(buffer)
    assert rows["Core 1"][0] == LAMP_COLORS[CoreState.WORKING]
    assert rows["Core 2"][0] == LAMP_COLORS[CoreState.STANDBY]
    assert rows["Core 3"][0] == LAMP_COLORS[CoreState.DISABLED]
    assert len({rows[label][0] for label in rows}) == 3   # three distinct colors
    assert "+ Core Activity History " in full_text(buffer)


W, S, D = CoreState.WORKING, CoreState.STANDBY, CoreState.DISABLED


def test_buckets_spread_the_timescale_window_across_every_column_newest_last():
    history = tuple([S] * 10 + [W] * 4)
    buckets = CpuScreen._buckets(history, window=8, columns=4)   # last 8 samples, 2 per column
    assert buckets == [[S, S], [S, S], [W, W], [W, W]]


def test_buckets_leave_the_left_empty_while_history_is_shorter_than_the_window():
    buckets = CpuScreen._buckets((W, W), window=8, columns=4)
    assert buckets == [[], [], [], [W, W]]


def test_chart_cell_shades_by_how_much_of_the_column_the_core_was_working():
    assert CpuScreen._chart_cell([]) is None
    assert CpuScreen._chart_cell([S, S, S, S]) is None
    assert CpuScreen._chart_cell([W, S, S, S])[0] == "░"   # ░ 25%
    assert CpuScreen._chart_cell([W, W, S, S])[0] == "▒"   # ▒ 50%
    assert CpuScreen._chart_cell([W, W, W, S])[0] == "▓"   # ▓ 75%
    assert CpuScreen._chart_cell([W, W, W, W]) == ("█", LAMP_COLORS[W])
    assert CpuScreen._chart_cell([D, D, D, W]) == ("-", LAMP_COLORS[D])


def test_activity_chart_puts_the_newest_activity_on_the_right_edge():
    history = tuple([S] * 39 + [W])            # 20 s window at 0.5 s/sample = 40 samples
    screen, buffer, *_ = make_screen([CoreView("Core 1", W, history=history)])
    chart = [char for char, _ in _chart_rows(buffer)["Core 1"][1]]
    assert chart[-1] != " " and all(char == " " for char in chart[:-1])


def test_timescale_option_sits_in_the_charts_bottom_border_and_cycles():
    history = tuple([W] * 40 + [S] * 40)      # working, then 20 s of standby
    screen, buffer, *_ = make_screen([CoreView("Core 1", S, history=history)])
    border_row = next(r for r in range(buffer.rows) if " Timescale: " in row_text(buffer, r))
    assert f"< {TIMESCALES[0][0]} >" in row_text(buffer, border_row)
    assert " now " in row_text(buffer, border_row)
    assert all(char == " " for char, _ in _chart_rows(buffer)["Core 1"][1])   # 20 s: only the standby part

    screen.handle_motion(key.MOTION_UP)         # from Core 1 up to the timescale
    screen.handle_motion(key.MOTION_RIGHT)      # -> 1 min, which reaches back into the working part
    assert f"< {TIMESCALES[1][0]} >" in row_text(buffer, border_row)
    assert any(char != " " for char, _ in _chart_rows(buffer)["Core 1"][1])

    screen.handle_motion(key.MOTION_LEFT)
    screen.handle_motion(key.MOTION_LEFT)       # wraps around to the longest
    assert f"< {TIMESCALES[-1][0]} >" in row_text(buffer, border_row)


def test_selection_starts_on_the_first_core_not_the_timescale():
    screen, buffer, manager, toggled, _ = make_screen([CoreView("Core 1", S)])
    screen.handle_enter()
    assert toggled == [0]


def test_cpu_screen_lays_cores_out_in_rows_of_two_with_a_sprite_each():
    cores = [CoreView(f"Core {i + 1}", CoreState.STANDBY) for i in range(5)]
    screen, buffer, *_ = make_screen(cores)
    anchors = sorted(buffer.sprites)
    assert len(anchors) == 5
    rows = sorted({row for _, row in anchors})
    assert len(rows) == 3                                        # 2 + 2 + 1
    assert len({col for col, _ in anchors}) == 2


def test_cpu_screen_shows_at_most_eight_cores():
    cores = [CoreView(f"Core {i + 1}", CoreState.STANDBY) for i in range(12)]
    screen, buffer, *_ = make_screen(cores, rows=40)
    assert len(buffer.sprites) == 8
    assert "Core 9" not in full_text(buffer)


def test_cpu_screen_names_the_process_a_working_core_is_busy_with():
    screen, buffer, *_ = make_screen([CoreView("Core 1", CoreState.WORKING, "bash (2)")])
    assert "Working: bash (2)" in full_text(buffer)


def test_only_working_cores_spin():
    cores = [CoreView("Core 1", CoreState.WORKING, "x (1)"), CoreView("Core 2", CoreState.STANDBY)]
    screen, buffer, *_ = make_screen(cores)
    working_anchor, idle_anchor = screen._sprite_anchors[0], screen._sprite_anchors[1]

    screen._animate(0.1)
    screen._animate(0.1)

    assert buffer.sprites[working_anchor] == "core_2"
    assert buffer.sprites[idle_anchor] == "core_0"


def test_left_right_on_a_selected_core_toggles_it():
    cores = [CoreView("Core 1", CoreState.STANDBY), CoreView("Core 2", CoreState.STANDBY)]
    screen, buffer, manager, toggled, _ = make_screen(cores)
    screen.handle_motion(key.MOTION_DOWN)
    screen.handle_motion(key.MOTION_RIGHT)
    screen.handle_enter()
    assert toggled == [1, 1]


def test_the_toggle_sits_right_next_to_its_core_and_shows_disabled_state():
    screen, buffer, *_ = make_screen([CoreView("Core 1", CoreState.DISABLED)])
    assert "Core 1  < Disabled >" in full_text(buffer)


def test_options_box_sits_right_of_the_cores_and_steps_with_left_right():
    value = {"oc": 100}
    options = [SettingOption("Overclock (all cores)", get_value=lambda: f"{value['oc']}%",
                             on_left=lambda: value.update(oc=value["oc"] - 10),
                             on_right=lambda: value.update(oc=value["oc"] + 10))]
    screen, buffer, *_ = make_screen([CoreView("Core 1", CoreState.STANDBY)], options=options)
    screen.handle_motion(key.MOTION_DOWN)     # past the one core onto the option
    screen.handle_motion(key.MOTION_RIGHT)
    assert value["oc"] == 110
    text = full_text(buffer)
    assert "< 110% >" in text
    options_row = next(r for r in range(buffer.rows) if "+ Options " in row_text(buffer, r))
    assert row_text(buffer, options_row).index("+ Options ") > row_text(buffer, options_row).index("+ Core Activity ")


def test_escape_leaves_the_cpu_screen():
    screen, buffer, manager, *_ = make_screen([CoreView("Core 1", CoreState.STANDBY)])
    with patch("pyglet.clock.unschedule"):
        screen.handle_key(key.ESCAPE, 0)
    assert manager.active is None


# --- sprite scaling ---

def test_sprites_scale_by_whole_factors_without_resampling(tmp_path):
    Image.fromarray(np.array([[[255, 0, 0, 255], [0, 255, 0, 255]]], dtype=np.uint8), "RGBA").save(tmp_path / "tiny.png")
    atlas = SpriteAtlas(tmp_path)
    scaled = atlas.get("tiny", scale=3)
    assert scaled.shape == (3, 6, 4)
    assert (scaled[:, :3, 0] == 255).all() and (scaled[:, 3:, 1] == 255).all()
    assert atlas.get("tiny").shape == (1, 2, 4)
