from dataclasses import dataclass, field

from horus.events.bus import EventBus
from horus.filesystem.vfs import VFS

@dataclass
class Context:
    """Bundles everything a command needs to execute: who's running it,
    where they are, and what systems they can reach. Passed into every
    command handler as the first argument."""
    
    session_id: str
    user: str
    cwd: str
    env: dict[str, str] = field(default_factory=dict)
    
    fs: VFS = None
    events: EventBus = None
    
    def publish(self, event) -> None:
        """Publish an event to the event bus."""
        if self.events is not None:
            self.events.publish(event)
            
    def resolve_path(self, path: str) -> str:
        """Resolve a path relative to the current working directory."""
        if self.fs is None:
            raise RuntimeError("Filesystem not set in context")
        return self.fs.resolve_path(self.cwd, path)