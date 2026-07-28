from horus.kernel.registry import Registry
from horus.events.bus import EventBus
from horus.session.context import Context
from horus.events.types import CommandExecutedEvent
import shlex
import logging


logger = logging.getLogger(__name__)

class Kernel:

    def __init__(self, registry: Registry, bus: EventBus):
        self.registry = registry
        self.bus = bus

    def execute(self, raw_line: str, ctx: Context):
        line = raw_line.strip()

        if not line:
            return
        
        try:
            tokens = shlex.split(line)
        except ValueError as e:
            ctx.write_line(f"Parse error: {e}")
            return

        command_name, *argv = tokens
        handler = self.registry.lookup(command_name)

        if handler is None:
            ctx.write_line(f"{command_name}: Command not found")
            return

        try:
            handler(ctx, argv)
        except Exception:
            logger.exception(f"command '{command_name}' raised an exception")
            ctx.write_line(f"{command_name}: internal error")
            return
        
        self.bus.publish(CommandExecutedEvent(command=command_name, args=argv, user=ctx.user, session_id= ctx.session_id))