"""System-wide reactions to process lifecycle events -- things that should
happen no matter *what* killed a process."""

from horus.events.bus import EventBus
from horus.events.types import ProcessKilledEvent
from horus.ui.crash_screen import CrashScreen


def register_system_reactions(bus: EventBus, screens, window, sounds, buffer) -> None:
    """Subscribes to ProcessKilledEvent so killing a critical process (e.g.
    init, PID 1) crashes the system."""

    def _on_process_killed(event: ProcessKilledEvent) -> None:
        if not event.critical:
            return
        if sounds is not None:
            sounds.set_sound_volume("system_crashed", 0.5)
            sounds.play("system_crashed")
            sounds.play("process_kill_buzz")
        if screens is not None:
            screens.push(CrashScreen(buffer, window, event.name))

    bus.subscribe(ProcessKilledEvent, _on_process_killed)
