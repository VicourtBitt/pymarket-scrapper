"""Application logging configuration shared by the scraper entry points."""

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Union


def configure_logging(
    log_directory: Union[str, Path] = "logs",
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
) -> logging.Logger:
    """Configure application logging once and return the application logger.

    File names contain the setup timestamp and are rotated when they reach
    ``max_bytes``.  ``log_directory`` is application-controlled; it must not
    be used to construct paths from untrusted request data.
    """
    directory = Path(log_directory)
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pymarket_scrapper")
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        file_handler = RotatingFileHandler(
            directory / f"pymarket-scrapper-{timestamp}.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
