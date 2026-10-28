"""Offline tests for the Typer entry point."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from typer.testing import CliRunner

import main
from models import ProductItem


def test_cli_exposes_expected_options_without_starting_services() -> None:
    result = CliRunner().invoke(main.app, ["--help"], terminal_width=300)

    assert result.exit_code == 0
    for option in (
        "--extraction",
        "--search",
        "--limit",
        "--marketplace",
        "--database-url",
    ):
        assert option in result.stdout


def test_cli_passes_defaults_and_mode_to_async_workflow(monkeypatch) -> None:
    received: dict[str, object] = {}

    async def fake_run(*args: object) -> None:
        received["args"] = args

    monkeypatch.setattr(main, "_run_cli", fake_run)
    result = CliRunner().invoke(
        main.app,
        [
            "--database-url", "sqlite:///test.db", "--extraction", "vendor",
            "--search", "x", "--limit", "3", "--marketplace", "amazon",
            "--sort-strategy", "relevance", "--recursive-vendors",
            "--storefront-products", "--headless",
            "--product-title-contains", "  seeds  ",
        ],
    )

    assert result.exit_code == 0
    args = received["args"]
    assert args[0] is main.ExtractionMode.VENDOR
    assert args[1:4] == ("x", 3, "amazon")
    assert args[4:8] == ("relevance", True, True, True)
    assert args[9] == "  seeds  "


def test_cli_product_filter_is_unrestricted_when_environment_is_unset_or_empty(
    monkeypatch,
) -> None:
    monkeypatch.delenv("PRODUCT_TITLE_CONTAINS", raising=False)
    assert main._cli_product_filter().title_contains is None

    monkeypatch.setenv("PRODUCT_TITLE_CONTAINS", "  ")
    assert main._cli_product_filter().title_contains is None

    monkeypatch.setenv("PRODUCT_TITLE_CONTAINS", " seeds ")
    assert main._cli_product_filter().title_contains == "seeds"


def test_cli_product_filter_option_takes_precedence_over_environment(monkeypatch) -> None:
    monkeypatch.setenv("PRODUCT_TITLE_CONTAINS", "environment")

    assert main._cli_product_filter(" command-line ").title_contains == "command-line"
    assert main._cli_product_filter("   ").title_contains is None


class _RecordingSink:
    def __init__(self) -> None:
        self.products: list[dict[str, Any]] = []

    def load_product(self, product: dict[str, Any]) -> None:
        self.products.append(product)


class _PassThroughFilter:
    async def process(
        self, stream: AsyncIterator[ProductItem]
    ) -> AsyncIterator[ProductItem]:
        async for product in stream:
            yield product


async def _search_products() -> AsyncIterator[ProductItem]:
    for product_id in ("product-1", "product-1", "product-2"):
        yield ProductItem(
            product_id=product_id,
            title=f"Product {product_id}",
            url=f"https://example.test/{product_id}",
            price=1.0,
            currency="USD",
            vendor_id=None,
        )


def test_search_only_product_persistence_deduplicates_without_detail_work() -> None:
    sink = _RecordingSink()

    asyncio.run(
        main._persist_search_products(
            _search_products(), sink, _PassThroughFilter()  # type: ignore[arg-type]
        )
    )

    assert [product["product_id"] for product in sink.products] == [
        "product-1",
        "product-2",
    ]


def test_vendor_cli_logs_storefront_catalog_decision(monkeypatch, caplog) -> None:
    """Vendor mode explains whether the optional catalog phase will run."""
    events: list[str] = []

    class _Sink:
        def close(self) -> None:
            return None

    class _Filter:
        @classmethod
        def __class_getitem__(cls, item: object) -> type["_Filter"]:
            return cls

        def __init__(self, **kwargs: Any) -> None:
            return None

        def close(self) -> None:
            return None

    class _Page:
        pass

    class _Context:
        async def new_page(self) -> _Page:
            return _Page()

    class _Browser:
        async def new_context(self, **kwargs: Any) -> _Context:
            return _Context()

        async def close(self) -> None:
            return None

    class _Playwright:
        chromium: "_Playwright"

        def __init__(self) -> None:
            self.chromium = self

        async def __aenter__(self) -> "_Playwright":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def launch(self, **kwargs: Any) -> _Browser:
            return _Browser()

    class _Crawler:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def extract_search_items(self, *args: Any, **kwargs: Any) -> AsyncIterator[ProductItem]:
            if False:
                yield ProductItem(
                    product_id="unused",
                    title="unused",
                    url="https://example.test/unused",
                    price=1.0,
                    currency="USD",
                )

    monkeypatch.setattr(main, "configure_logging", lambda *args, **kwargs: logging.getLogger("test.vendor-cli"))
    monkeypatch.setattr(main, "MarketplaceConfig", type("_Config", (), {
        "from_marketplace": staticmethod(lambda *args, **kwargs: object()),
    }))
    monkeypatch.setattr(main, "PostgreSQLSink", lambda *args, **kwargs: _Sink())
    monkeypatch.setattr(main, "SQLFilter", _Filter)
    monkeypatch.setattr(main, "async_playwright", lambda: _Playwright())
    monkeypatch.setattr(main, "AmazonCrawler", _Crawler)
    monkeypatch.setattr(
        main,
        "_filter_search_products",
        lambda stream, product_filter: stream,
    )

    async def fake_resolve(*args: Any, **kwargs: Any) -> dict[str, dict[str, Any]]:
        return {}

    async def fake_process(*args: Any, **kwargs: Any) -> None:
        events.append("process")

    monkeypatch.setattr(main, "_resolve_vendors_from_search", fake_resolve)
    monkeypatch.setattr(main, "_process_vendor_catalogs", fake_process)

    caplog.set_level(logging.INFO, logger="test.vendor-cli")
    asyncio.run(
        main._run_cli(
            main.ExtractionMode.VENDOR,
            "seeds",
            1,
            "amazon",
            None,
            False,
            False,
            True,
            "sqlite:///test.db",
        )
    )

    assert events == []
    assert (
        "Vendor mode: catalog extraction skipped because "
        "--storefront-products was not supplied"
    ) in caplog.text

    asyncio.run(
        main._run_cli(
            main.ExtractionMode.VENDOR,
            "seeds",
            1,
            "amazon",
            None,
            False,
            True,
            True,
            "sqlite:///test.db",
        )
    )

    assert events == ["process"]
    assert "Vendor mode: about to process storefront catalogs" in caplog.text
