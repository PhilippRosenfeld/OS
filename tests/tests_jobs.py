from unittest.mock import patch

import pyglet
import pytest

from horus.apps.netman.commands import netman_commands
from horus.display.screen_buffer import ScreenBuffer
from horus.events.bus import EventBus
from horus.hardware.spec import HardwareSpec
from horus.kernel.kernel import Kernel
from horus.network.hosts import HostEntry, HostTable
from horus.network.netd import NetDaemon
from horus.processes.process import process as Process
from horus.processes.processTable import ProcessTable
from horus.session.context import Context
from horus.session.history import CommandHistory
from horus.shell.input_handler import InputHandler
from horus.shell.jobs import run_timed

key = pyglet.window.key


def full_text(buffer):
    return "\n".join("".join(buffer.get_cell(c, r).char for c in range(buffer.cols)).rstrip() for r in range(buffer.rows))


class ManualClock:
    """Stands in for pyglet.clock: scheduled callbacks only run when the
    test calls advance() -- so a test can look at the screen in between."""

    def __init__(self):
        self.pending = []      # [(fire_at, callback)]
        self.now = 0.0
        self.delays = []       # every delay ever scheduled, in order

    def schedule_once(self, callback, delay):
        self.delays.append(delay)
        self.pending.append((self.now + delay, callback))

    def unschedule(self, callback):
        self.pending = [(t, cb) for t, cb in self.pending if cb is not callback]

    def advance(self, seconds):
        self.now += seconds
        while True:
            due = [(t, cb) for t, cb in self.pending if t <= self.now + 1e-9]
            if not due:
                return
            entry = min(due, key=lambda e: e[0])
            self.pending.remove(entry)
            entry[1](0.0)

    def run_all(self):
        while self.pending:
            self.advance(max(t for t, _ in self.pending) - self.now)


@pytest.fixture
def clock():
    clock = ManualClock()
    with patch("pyglet.clock.schedule_once", clock.schedule_once), \
         patch("pyglet.clock.unschedule", clock.unschedule):
        yield clock


@pytest.fixture
def shell():
    """A shell with a '> ' prompt on a fresh buffer; returns (ctx, handler, buffer)."""
    buffer = ScreenBuffer(80, 30)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer)
    handler = InputHandler(buffer, CommandHistory(), get_prompt=lambda: "> ")
    ctx.input_handler = handler
    return ctx, handler, buffer


def say(ctx, text):
    return lambda: ctx.write_line(text)


# --- run_timed ---

def test_steps_appear_one_after_another_at_their_delay(clock, shell):
    ctx, handler, buffer = shell
    run_timed(ctx, [(1.0, say(ctx, "one")), (0.5, say(ctx, "two"))], finish=say(ctx, "done"))
    assert "one" not in full_text(buffer)
    clock.advance(1.0)
    assert "one" in full_text(buffer) and "two" not in full_text(buffer)
    clock.advance(0.5)
    assert "two" in full_text(buffer) and "done" in full_text(buffer)


def test_the_shell_is_busy_and_holds_its_prompt_until_the_job_ends(clock, shell):
    ctx, handler, buffer = shell
    buffer.cursor_row = 1                        # the command line was submitted, output starts below
    run_timed(ctx, [(1.0, say(ctx, "one"))])
    handler.start_line()                         # what the shell does right after the command returned
    assert handler.busy
    assert full_text(buffer).splitlines()[1] == ""           # no prompt yet
    clock.run_all()
    assert not handler.busy
    assert full_text(buffer).splitlines()[1:3] == ["one", ">"]   # prompt right after the output


def test_typing_and_enter_are_ignored_while_busy(clock, shell):
    ctx, handler, buffer = shell
    submitted = []
    handler._on_submit = submitted.append
    run_timed(ctx, [(1.0, say(ctx, "one"))])
    handler._handle_text("ls")
    handler._handle_enter()
    assert handler.current_line == "" and submitted == []
    clock.run_all()
    handler._handle_text("ls")
    assert handler.current_line == "ls"


def test_ctrl_c_stops_the_job_and_still_finishes(clock, shell):
    ctx, handler, buffer = shell
    run_timed(ctx, [(1.0, say(ctx, "one")), (1.0, say(ctx, "two"))], finish=say(ctx, "stats"))
    clock.advance(1.0)
    handler._handle_key(key.C, key.MOD_CTRL)
    clock.run_all()
    text = full_text(buffer)
    assert "one" in text and "two" not in text
    assert "^C" in text and "stats" in text
    assert not handler.busy


def test_steps_can_be_a_generator_deciding_as_they_go(clock, shell):
    ctx, handler, buffer = shell
    seen = []

    def steps():
        for i in range(3):
            yield i * 0.25, lambda i=i: seen.append(i)

    run_timed(ctx, steps())
    clock.run_all()
    assert seen == [0, 1, 2] and clock.delays == [0.0, 0.25, 0.5]


def test_without_an_input_handler_everything_runs_right_away():
    buffer = ScreenBuffer(40, 5)
    ctx = Context(session_id="s", user="root", cwd="/", screen=buffer)
    run_timed(ctx, [(5.0, say(ctx, "one"))], finish=say(ctx, "done"))
    assert "one" in full_text(buffer) and "done" in full_text(buffer)


# --- ping takes its time ---

@pytest.fixture
def ping_shell(shell):
    ctx, handler, buffer = shell
    hardware = HardwareSpec()
    hardware.motherboard.network_interfaces[0].ip_address = "192.168.1.2"
    hardware.motherboard.network_interfaces[0].latency_ms = 0
    hosts = HostTable({"slow.test": HostEntry(name="slow.test", ip="192.168.1.9", latency_ms=200.0)})
    processes = ProcessTable()
    processes.add_process(Process(name="netd", pid=0, owner="root"))
    ctx.hardware, ctx.host_table = hardware, hosts
    ctx.netd = NetDaemon(hardware, processes, hosts=hosts)
    kernel = Kernel(registry=netman_commands, bus=EventBus())
    return (lambda line: kernel.execute(line, ctx)), handler, buffer, hosts


def test_ping_prints_each_reply_after_its_round_trip(clock, ping_shell):
    run, handler, buffer, _ = ping_shell
    run("ping slow.test 3")
    assert "Pinging slow.test" in full_text(buffer) and "Reply" not in full_text(buffer)
    assert 0.16 <= clock.delays[0] <= 0.24                       # 200 ms +-20 %, no gap before the first
    clock.advance(clock.delays[0])
    assert full_text(buffer).count("Reply from") == 1
    clock.run_all()
    assert full_text(buffer).count("Reply from") == 3
    assert all(0.5 + 0.16 <= d <= 0.5 + 0.24 for d in clock.delays[1:])   # interval + round trip
    assert "Sent = 3, Received = 3" in full_text(buffer) and not handler.busy


def test_a_lost_packet_waits_for_the_timeout(clock, ping_shell):
    run, _, buffer, hosts = ping_shell
    hosts.get_host("slow.test").online = False
    run("ping slow.test 2")
    clock.run_all()
    assert clock.delays == [1.0, 1.5]
    assert full_text(buffer).count("Request timed out.") == 2


def test_ctrl_c_stops_ping_with_statistics_for_what_was_sent(clock, ping_shell):
    run, handler, buffer, _ = ping_shell
    run("ping slow.test 10")
    clock.advance(clock.delays[0])
    handler._handle_key(key.C, key.MOD_CTRL)
    text = full_text(buffer)
    assert text.count("Reply from") == 1 and "^C" in text
    assert "Sent = 1, Received = 1, Lost = 0" in text
    assert not handler.busy


def test_ping_stopped_before_the_first_reply_prints_no_statistics(clock, ping_shell):
    run, handler, buffer, _ = ping_shell
    run("ping slow.test")
    handler._handle_key(key.C, key.MOD_CTRL)
    assert "^C" in full_text(buffer) and "statistics" not in full_text(buffer)
