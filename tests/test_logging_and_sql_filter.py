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


def test_sql_title_filter_treats_like_metacharacters_literally() -> None:
    import asyncio

    from models import ProductItem
    from models.config import ProductFilter
    from pipeline.sql_filter import SQLFilter

    titles = ["1000 seeds", "100% seeds", "axb", "a_b", r"c:\x", "cxx"]

    def matching(value: str) -> list[str]:
        product_filter = ProductFilter(title_contains=value)
        sql_filter = SQLFilter[ProductItem](model_class=ProductItem, filters=product_filter)

        async def source():
            for index, title in enumerate(titles):
                yield ProductItem(
                    product_id=str(index), title=title, url=None,
                    price=1.0, currency="BRL", vendor_id=None,
                )

        async def collect() -> list[str]:
            return [item.title async for item in sql_filter.process(source())]

        try:
            result = asyncio.run(collect())
        finally:
            sql_filter.close()
        # SQL and in-memory semantics must agree.
        assert result == [title for title in titles if product_filter.matches(title)]
        return result

    assert matching("100%") == ["100% seeds"]
    assert matching("a_b") == ["a_b"]
    assert matching(r"c:\x") == [r"c:\x"]
    assert matching("SEEDS") == ["1000 seeds", "100% seeds"]


def test_regex_extractor_returns_whole_matches_in_first_seen_order() -> None:
    from pipeline.regex_engine import RegexExtractor

    extractor = RegexExtractor({
        "phones": r"\(?(\d{2})\)? ?(\d{4,5})-?(\d{4})",
        "emails": r"[\w.+-]+@[\w-]+\.[\w.]+",
    })

    result = extractor.extract(
        "Call (31) 99760-6208 or b@x.com, a@y.com; again (31) 99760-6208 b@x.com"
    )

    assert result == {
        "phones": ["(31) 99760-6208"],
        "emails": ["b@x.com", "a@y.com"],
    }
    assert extractor.extract("nothing here") == {}
    assert RegexExtractor({"digits": r"\d*"}).extract("tel 31 e 31") == {"digits": ["31"]}
