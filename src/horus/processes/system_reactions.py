"""System-wide reactions to process lifecycle events -- things that should
happen no matter *what* killed a process."""

from horus.display.status_bar import StatusBar
from horus.events.bus import EventBus
from horus.events.system_log import SystemLog
from horus.events.types import (
    MemoryCheckedEvent,
    MemoryErrorEvent,
    PowerUsageCheckedEvent,
    ProcessKilledEvent,
    StorageActivityCheckedEvent,
    TemperatureCriticalEvent,
    TemperatureWarningEvent,
)
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

# Drive grinding noise (see register_storage_reactions): silent below
# _GRIND_THRESHOLD activity -- just above what the drives idle at with the
# seeded processes -- then ramping from _GRIND_MIN_VOLUME up to full volume
# as activity approaches 1.0.
_GRIND_SOUND = "grinding-noise-from-a-hdd"
_GRIND_THRESHOLD = 0.15
_GRIND_MIN_VOLUME = 0.2
_GRIND_FADE_OUT_SECONDS = 1.0


def register_storage_reactions(bus: EventBus, sounds) -> None:
    """Subscribes to StorageActivityCheckedEvent so busy drives are audible:
    once activity crosses _GRIND_THRESHOLD, the HDD grinding noise starts
    looping, its volume following the activity on every tick; once it drops
    back below, the loop fades out and stops."""
    player = None

    def _on_storage_activity_checked(event: StorageActivityCheckedEvent) -> None:
        nonlocal player
        if sounds is None:
            return
        if event.activity < _GRIND_THRESHOLD:
            if player is not None:
                fading, player = player, None
                sounds.fade_out(0.0, duration=_GRIND_FADE_OUT_SECONDS, player=fading, on_complete=fading.pause)
            return
        ramp = (min(1.0, event.activity) - _GRIND_THRESHOLD) / (1.0 - _GRIND_THRESHOLD)
        sounds.set_sound_volume(_GRIND_SOUND, _GRIND_MIN_VOLUME + (1.0 - _GRIND_MIN_VOLUME) * ramp)
        if player is None or not player.playing:
            player = sounds.play_looped(_GRIND_SOUND)

    bus.subscribe(StorageActivityCheckedEvent, _on_storage_activity_checked)


def register_temperature_reactions(bus: EventBus, screens, window, sounds, buffer) -> None:
    """Subscribes to TemperatureCriticalEvent so when the system overheats,
    it crashes outright -- no process is singled out or killed, the whole
    system just goes down (see HardwareSpec._handle_thermal_shutdown).

    Only TemperatureCriticalEvent takes the system down (CrashScreen, same
    kernel-panic-and-close-the-window treatment as a critical process kill --
    see register_system_reactions) -- TemperatureWarningEvent just plays a
    sound. Unlike the SystemLog/status-bar reactions to the same event
    (which only want the edge, so as not to spam a log or leave a light
    stuck blinking), the sound deliberately keeps playing every tick spent
    over the warning threshold -- an ongoing overheat is worth an ongoing
    nag, not a single notification that goes quiet the moment you've
    acknowledged it once (e.g. by checking 'err')."""

    def _on_temperature_warning(event) -> None:
        if event.over_warning and sounds is not None:
            sounds.play("greece-eas-alarm")

    def _on_temperature_critical(event) -> None:
        if sounds is not None:
            sounds.play("system_crashed")
        if screens is not None:
            screens.push(CrashScreen(buffer, window, "System",
                                      reason=f"shut down due to critical temperature ({event.temperature:.1f}C)"))

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
            log.warning(f"System temperature warning at {event.temperature:.1f}C. System temperature will go critical at {event.critical_temperature:.1f}C and will start to shut down processes to prevent overheating.")
        was_over_warning = event.over_warning  # tracks the edge, not just the first crossing --
                                                # recovering and going over the warning threshold again logs again

    def _on_temperature_critical(event: TemperatureCriticalEvent) -> None:
        log.error(f"System temperature critical at {event.temperature:.1f}C")

    def _on_memory_error(event: MemoryErrorEvent) -> None:
        if event.kind == "corrected":
            log.warning(event.detail)
        else:
            log.error(event.detail)

    bus.subscribe(PowerUsageCheckedEvent, _on_power_usage_checked)
    bus.subscribe(ProcessKilledEvent, _on_process_killed)
    bus.subscribe(TemperatureWarningEvent, _on_temperature_warning)
    bus.subscribe(TemperatureCriticalEvent, _on_temperature_critical)
    bus.subscribe(MemoryErrorEvent, _on_memory_error)


def register_status_bar(bus: EventBus, status_bar: StatusBar) -> None:
    """Drives the PWR/TEMP/SYS indicator lights on `status_bar` from the same
    events that feed the SystemLog -- PWR and TEMP both auto-clear (they just
    mirror the event's own current over_budget/over_warning flag, no
    edge-tracking needed here since both now always reflect live state, unlike
    the log which only wants the transition). SYS latches on a critical
    process kill; there's no meaningful 'recovered' event for that (the
    system crashes shortly after -- see register_system_reactions), so it
    doesn't auto-clear. Once lit, a light actually blinks via
    StatusBar.start_blinking(), not anything done here. MSC lights while
    memory is being swapped out (see MemoryManager) and turns off once
    everything fits in RAM again."""

    def _on_power_usage_checked(event: PowerUsageCheckedEvent) -> None:
        status_bar.set_lit("PWR", event.over_budget)

    def _on_process_killed(event: ProcessKilledEvent) -> None:
        if event.critical:
            status_bar.set_lit("SYS", True)

    def _on_temperature_warning(event: TemperatureWarningEvent) -> None:
        status_bar.set_lit("TEMP", event.over_warning)

    def _on_memory_checked(event: MemoryCheckedEvent) -> None:
        status_bar.set_lit("MSC", event.swap_used_kb > 0)

    bus.subscribe(PowerUsageCheckedEvent, _on_power_usage_checked)
    bus.subscribe(ProcessKilledEvent, _on_process_killed)
    bus.subscribe(TemperatureWarningEvent, _on_temperature_warning)
    bus.subscribe(MemoryCheckedEvent, _on_memory_checked)


def register_memory_reactions(bus: EventBus, sounds) -> None:
    """Audible memory trouble: a quiet notification for a corrected error,
    the harsher system error sound when a process got killed (OOM, crash)
    or a file corrupted. A memory error that kills a critical process
    already crashes the system via register_system_reactions."""

    def _on_memory_error(event: MemoryErrorEvent) -> None:
        if sounds is None:
            return
        sounds.play("error_notification" if event.kind == "corrected" else "system_error_notification")

    bus.subscribe(MemoryErrorEvent, _on_memory_error)
