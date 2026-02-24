"""Structured logging configuration with Rich console output.

Provides a single setup function that configures the root logger with
a Rich handler for human-readable console output and optional JSON
formatting for machine consumption.
"""

from __future__ import annotations

import logging
import sys

from rich.console import Console
from rich.logging import RichHandler

_configured = False


def setup_logging(level: str = "INFO") -> None:
    """Configure application-wide logging with Rich formatting.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR).
               Applied to the root logger and all application loggers.
    """
    global _configured
    if _configured:
        return
    _configured = True

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    console = Console(stderr=True)
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
    )
    rich_handler.setLevel(numeric_level)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()
    root_logger.addHandler(rich_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Create a named logger scoped to the application namespace.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A configured logger instance.
    """
    return logging.getLogger(f"ai_code_reviewer.{name}")
