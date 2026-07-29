import logging
import sys


def setup_logging(level: int = logging.INFO, log_file: str | None = None) -> None:
    """Call this once, at program startup (in __main__.py), before
    anything else logs. Configures the root logger; every module's
    logging.getLogger(__name__) inherits this configuration automatically."""
    
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())
        if not isinstance(level, int):
            raise ValueError(f"Unknown log level: {level!r}")

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )