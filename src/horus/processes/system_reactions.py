"""System-wide reactions to process lifecycle events -- things that should
happen no matter *what* killed a process."""

from horus.display.status_bar import StatusBar
from horus.events.bus import EventBus
from horus.events.system_log import SystemLog
from horus.events.types import PowerUsageCheckedEvent, ProcessKilledEvent, TemperatureCriticalEvent, TemperatureWarningEvent
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
    
def register_power_reactions(bus: EventBus, sounds) -> None:
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

def register_temperature_reactions(bus: EventBus, screens, window, sounds, buffer) -> None:
    """Subscribes to TemperatureCriticalEvent so when the system overheats, it
    kills a random process and plays a sound. This is a placeholder for a more
    sophisticated thermal management system that would eventually exist.

    Only TemperatureCriticalEvent takes the system down (CrashScreen, same
    kernel-panic-and-close-the-window treatment as a critical process kill --
    see register_system_reactions) -- TemperatureWarningEvent just plays a
    sound. TemperatureWarningEvent now fires every tick regardless of
    over_warning (see its own docstring), so this tracks the edge itself --
    otherwise it'd replay the sound on every tick spent over the warning
    threshold instead of once when crossing into it."""
    was_over_warning = False

    def _on_temperature_warning(event) -> None:
        nonlocal was_over_warning
        if event.over_warning and not was_over_warning:
            if sounds is not None:
                sounds.play("greece-eas-alarm")
        was_over_warning = event.over_warning

    def _on_temperature_critical(event) -> None:
        if sounds is not None:
            sounds.play("system_crashed")
        if screens is not None:
            screens.push(CrashScreen(buffer, window, event.process_killed.name,
                                      reason=f"killed due to critical temperature ({event.temperature:.1f}C)"))

    bus.subscribe(TemperatureCriticalEvent, _on_temperature_critical)
    bus.subscribe(TemperatureWarningEvent, _on_temperature_warning)

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
            
    was_over_warning = False

    def _on_temperature_warning(event: TemperatureWarningEvent) -> None:
        nonlocal was_over_warning
        if event.over_warning and not was_over_warning:
            log.warning(f"System temperature warning at {event.temperature:.1f}C. System is close to critical temperature {event.critical_temperature:.1f}C soon and will start to shut down processes to prevent overheating.")
        was_over_warning = event.over_warning  # tracks the edge, not just the first crossing --
                                                # recovering and going over the warning threshold again logs again

    def _on_temperature_critical(event: TemperatureCriticalEvent) -> None:
        log.error(f"System temperature critical at {event.temperature:.1f}C")

    bus.subscribe(PowerUsageCheckedEvent, _on_power_usage_checked)
    bus.subscribe(ProcessKilledEvent, _on_process_killed)
    bus.subscribe(TemperatureWarningEvent, _on_temperature_warning)
    bus.subscribe(TemperatureCriticalEvent, _on_temperature_critical)


def register_status_bar(bus: EventBus, status_bar: StatusBar) -> None:
    """Drives the PWR/TEMP/SYS indicator lights on `status_bar` from the same
    events that feed the SystemLog -- PWR and TEMP both auto-clear (they just
    mirror the event's own current over_budget/over_warning flag, no
    edge-tracking needed here since both now always reflect live state, unlike
    the log which only wants the transition). SYS latches on a critical
    process kill; there's no meaningful 'recovered' event for that (the
    system crashes shortly after -- see register_system_reactions), so it
    doesn't auto-clear. Once lit, a light actually blinks via
    StatusBar.start_blinking(), not anything done here. MSC still has no
    real trigger yet."""

    def _on_power_usage_checked(event: PowerUsageCheckedEvent) -> None:
        status_bar.set_lit("PWR", event.over_budget)

    def _on_process_killed(event: ProcessKilledEvent) -> None:
        if event.critical:
            status_bar.set_lit("SYS", True)

    def _on_temperature_warning(event: TemperatureWarningEvent) -> None:
        status_bar.set_lit("TEMP", event.over_warning)

    bus.subscribe(PowerUsageCheckedEvent, _on_power_usage_checked)
    bus.subscribe(ProcessKilledEvent, _on_process_killed)
    bus.subscribe(TemperatureWarningEvent, _on_temperature_warning)
