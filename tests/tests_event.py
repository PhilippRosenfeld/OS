from horus.events.bus import EventBus
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