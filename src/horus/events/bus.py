import logging
from collections import defaultdict
from typing import Callable, TypeVar

from .types import Event

logger = logging.getLogger(__name__)

E = TypeVar("E", bound=Event)
Handler = Callable[[E], None]

class EventBus:
    """Synchronous publish-subscribe bus. Kernel and commands publish events;
    story/malware/logging modules subscribe to react to them."""

    def __init__(self) -> None:
        self._handlers: defaultdict[type[Event], list[Handler]] = defaultdict(list)
        
    def subscribe(self, event_type: type[E], handler: Handler[E]) -> Callable[[], None]:
        """Register handler for event_type. Returns an unsubscribe callback."""
        self._handlers[event_type].append(handler)
        def _unsubscribe() -> None:
            self.unsubscribe(event_type, handler)
        return _unsubscribe

    def unsubscribe(self, event_type: type[E], handler: Handler[E]) -> None:
        """Remove a previously registered handler. No-op if not found."""
        handlers = self._handlers.get(event_type)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def publish(self, event: Event) -> None:
        """Dispatch event to all handlers registered for its exact type.
        Each handler call is isolated: exceptions are caught and logged,
        never propagated to the caller."""
        event_type = type(event)
        for handler in self._get_handlers(event_type):
            try:
                handler(event)
            except Exception as e:
                logger.exception(
                    "Exception in event handler %s for event %s: %s", handler, event, e
                )
        
    def _get_handlers(self, event_type: type[E]) -> list[Handler[E]]:
        """Return a copy of the list of handlers for event_type."""
        result: list[Handler] = []
        for cls in event_type.__mro__:
            result.extend(self._handlers.get(cls, []))
        return result
        
    def clear(self) -> None:
        """Remove all handlers for all event types."""
        self._handlers.clear()