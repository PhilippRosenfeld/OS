from horus.events.system_log import SystemLog
from horus.kernel.registry import command
from horus.ui.screens.detail_screen import DetailScreen


def _log_lines(ctx) -> list[str]:
    """Newest entries first -- DetailScreen/draw_box silently drops
    whatever doesn't fit the screen height, so if the log is longer than
    that, it's the *oldest* entries that should disappear, not the newest."""
    log = ctx.system_log if ctx.system_log is not None else SystemLog()
    entries = list(reversed(log.entries()))
    if not entries:
        return ["No warnings or errors."]
    return [f"[{entry.severity.value}] {entry.timestamp:%H:%M:%S}  {entry.message}" for entry in entries]


@command("err", help_text="Show system warnings and errors", category="system")
def err(ctx, argv: list[str]) -> None:
    ctx.screens.push(DetailScreen(ctx.screen, "Warnings & Errors", _log_lines(ctx), ctx.screens,
                                   refresh=lambda: _log_lines(ctx)))
