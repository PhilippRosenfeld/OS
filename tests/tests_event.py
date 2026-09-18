from horus.events.bus import EventBus
from horus.events.system_log import LogSeverity, SystemLog
from horus.events.types import CommandExecutedEvent


def test_publish_calls_subscribed_handler():
    bus = EventBus()
    received = []
    bus.subscribe(CommandExecutedEvent, received.append)

    event = CommandExecutedEvent(command="ls", args=[], user="root", session_id="s1")
    bus.publish(event)

    assert received == [event]

def test_handler_exception_does_not_propagate():
    bus = EventBus()
    def broken_handler(e): raise ValueError("boom")
    bus.subscribe(CommandExecutedEvent, broken_handler)

    bus.publish(CommandExecutedEvent(command="ls", args=[], user="root", session_id="s1"))
    # should not raise


# --- SystemLog ---

def test_system_log_starts_empty():
    log = SystemLog()
    assert len(log) == 0
    assert log.entries() == []


def test_system_log_warning_records_a_warning_entry():
    log = SystemLog()
    log.warning("power usage exceeded PSU output")
    entry = log.entries()[0]
    assert entry.severity is LogSeverity.WARNING
    assert entry.message == "power usage exceeded PSU output"


def test_system_log_error_records_an_error_entry():
    log = SystemLog()
    log.error("critical process killed")
    entry = log.entries()[0]
    assert entry.severity is LogSeverity.ERROR
    assert entry.message == "critical process killed"


def test_system_log_entries_are_ordered_oldest_first():
    log = SystemLog()
    log.warning("first")
    log.error("second")
    assert [e.message for e in log.entries()] == ["first", "second"]


def test_system_log_drops_the_oldest_entry_once_full():
    log = SystemLog(maxlen=2)
    log.warning("first")
    log.warning("second")
    log.warning("third")
    assert [e.message for e in log.entries()] == ["second", "third"]
    assert len(log) == 2