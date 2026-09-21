"""System-wide reactions to process lifecycle events -- things that should
happen no matter *what* killed a process."""

from horus.display.status_bar import StatusBar
from horus.events.bus import EventBus
from horus.events.system_log import SystemLog
from horus.events.types import PowerUsageCheckedEvent, ProcessKilledEvent
from horus.ui.screens.crash_screen import CrashScreen


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
    
def register_power_reactions(bus: EventBus, screens, window, sounds, buffer) -> None:
    was_over_budget = False

    def _on_power_usage_checked(event: PowerUsageCheckedEvent) -> None:
        nonlocal was_over_budget
        if not event.over_budget:
            if was_over_budget:
                was_over_budget = False
            return
        if was_over_budget:
            return  # only react on the edge, not every time the event fires while still over budget
        was_over_budget = True
        if sounds is not None:
            sounds.play("system_error_notification")

    bus.subscribe(PowerUsageCheckedEvent, _on_power_usage_checked)


def register_system_log(bus: EventBus, log: SystemLog) -> None:
    """Feeds `log` from events that represent something going wrong, for the
    'err' command's log viewer -- independent of register_system_reactions()/
    register_power_reactions() above (which play sounds/push screens), so
    the log works regardless of whether those are wired up."""
    was_over_budget = False

    def _on_power_usage_checked(event: PowerUsageCheckedEvent) -> None:
        nonlocal was_over_budget
        if event.over_budget and not was_over_budget:
            log.warning(f"Power usage exceeded PSU output: "
                        f"{event.total_power_usage:.0f}/{event.psu_output_watts:.0f} W")
        was_over_budget = event.over_budget  # tracks the edge, not just the first crossing --
                                              # recovering and going over budget again logs again

    def _on_process_killed(event: ProcessKilledEvent) -> None:
        if event.critical:
            log.error(f"Critical process '{event.name}' (PID {event.pid}) "
                      f"was killed by {event.killed_by} -- system crashed")

    bus.subscribe(PowerUsageCheckedEvent, _on_power_usage_checked)
    bus.subscribe(ProcessKilledEvent, _on_process_killed)


def register_status_bar(bus: EventBus, status_bar: StatusBar) -> None:
    """Drives the PWR/SYS indicator lights on `status_bar` from the same
    events that feed the SystemLog -- PWR auto-clears when usage drops back
    under budget (it just mirrors the event's own current over_budget flag,
    no edge-tracking needed here since it always reflects live state, unlike
    the log which only wants the transition). SYS latches on a critical
    process kill; there's no meaningful 'recovered' event for that (the
    system crashes shortly after -- see register_system_reactions), so it
    doesn't auto-clear. TEMP/MSC have no real trigger yet -- they simply
    never light up until something exists to drive them."""

    def _on_power_usage_checked(event: PowerUsageCheckedEvent) -> None:
        status_bar.set_lit("PWR", event.over_budget)

    def _on_process_killed(event: ProcessKilledEvent) -> None:
        if event.critical:
            status_bar.set_lit("SYS", True)

    bus.subscribe(PowerUsageCheckedEvent, _on_power_usage_checked)
    bus.subscribe(ProcessKilledEvent, _on_process_killed)
