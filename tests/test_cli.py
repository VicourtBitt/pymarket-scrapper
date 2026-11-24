"""Offline tests for the Typer entry point."""

from typer.testing import CliRunner

import main
from pipeline import ExtractionMode


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
    assert args[0] is ExtractionMode.VENDOR
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


def test_run_cli_wires_crawlers_and_workflow_options(monkeypatch) -> None:
    """_run_cli builds both crawlers and forwards CLI options to the workflow."""
    import asyncio
    import logging
    from typing import Any

    received: dict[str, Any] = {}

    class _Closeable:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        @classmethod
        def __class_getitem__(cls, item: object) -> type:
            return cls

        def close(self) -> None:
            received.setdefault("closed", 0)
            received["closed"] += 1

    class _Browser:
        async def new_context(self, **kwargs: Any) -> "_Browser":
            return self

        async def new_page(self) -> object:
            return object()

        async def close(self) -> None:
            received["browser_closed"] = True

    class _Playwright:
        def __init__(self) -> None:
            self.chromium = self

        async def __aenter__(self) -> "_Playwright":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def launch(self, **kwargs: Any) -> _Browser:
            received["headless"] = kwargs["headless"]
            return _Browser()

    class _Workflow:
        def __init__(self, **kwargs: Any) -> None:
            received["components"] = sorted(kwargs)

        async def run(self, mode: Any, search: str, **kwargs: Any) -> None:
            received["run"] = (mode, search, kwargs)

    monkeypatch.setattr(main, "configure_logging", lambda *a, **k: logging.getLogger("test.cli"))
    monkeypatch.setattr(main.MarketplaceConfig, "from_marketplace", staticmethod(lambda *a, **k: object()))
    monkeypatch.setattr(main, "PostgreSQLSink", _Closeable)
    monkeypatch.setattr(main, "SQLFilter", _Closeable)
    monkeypatch.setattr(main, "async_playwright", _Playwright)
    monkeypatch.setattr(main, "AmazonCrawler", lambda *a: "crawler")
    monkeypatch.setattr(main, "AmazonVendorCrawler", lambda *a: "vendor_crawler")
    monkeypatch.setattr(main, "ExtractionWorkflow", _Workflow)

    asyncio.run(main._run_cli(
        ExtractionMode.VENDOR, "seeds", 3, "amazon", "relevance",
        True, False, True, "sqlite:///test.db",
    ))

    assert received["headless"] is True
    assert received["components"] == [
        "crawler", "logger", "product_filter", "sink", "sql_filter", "vendor_crawler",
    ]
    assert received["run"] == (
        ExtractionMode.VENDOR,
        "seeds",
        {
            "limit": 3,
            "sort_strategy": "relevance",
            "storefront_products": False,
            "recursive_vendors": True,
            "run_request": received["run"][2]["run_request"],
        },
    )
    run_request = received["run"][2]["run_request"]
    assert run_request.marketplace == "amazon"
    assert run_request.source == "cli"
    assert run_request.metadata["extraction"] == "vendor"
    assert received["browser_closed"] is True
    assert received["closed"] == 2
