"""Offline tests for logging setup and trusted SQL filtering."""

import asyncio
import logging
from pathlib import Path

import pytest

from include import configure_logging
from models import ProductItem
from pipeline.sql_filter import SQLFilter


def test_configure_logging_creates_timestamped_rotating_file(tmp_path: Path) -> None:
    logger_name = "pymarket_scrapper"
    logger = logging.getLogger(logger_name)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    logger = configure_logging(tmp_path, max_bytes=1, backup_count=1)
    logger.info("first")
    logger.info("second")
    for handler in logger.handlers:
        handler.flush()

    files = list(tmp_path.glob("pymarket-scrapper-*.log"))
    assert files
    assert len(logger.handlers) == 2
    assert any(path.name.endswith(".log.1") for path in tmp_path.iterdir())


def test_crawler_child_logger_reaches_configured_file(tmp_path: Path) -> None:
    root_logger = logging.getLogger("pymarket_scrapper")
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    configure_logging(tmp_path, max_bytes=1024 * 1024)
    crawler_logger = logging.getLogger("pymarket_scrapper.crawlers.amazon")
    crawler_logger.warning("crawler warning")

    for handler in root_logger.handlers:
        handler.flush()
    log_files = list(tmp_path.glob("pymarket-scrapper-*.log"))
    assert log_files
    assert "crawler warning" in log_files[0].read_text(encoding="utf-8")


def test_sql_filter_retains_raw_where_clause_and_propagates_sql_errors() -> None:
    sql_filter = SQLFilter[ProductItem](ProductItem, where_clause="NOT_VALID SQL")

    async def stream():
        yield ProductItem(
            product_id="1", title="item", url=None, price=1, currency="R$"
        )

    with pytest.raises(Exception):
        asyncio.run(sql_filter.process(stream()).__anext__())
    sql_filter.close()
