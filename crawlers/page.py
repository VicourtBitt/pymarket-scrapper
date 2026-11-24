"""Playwright page helpers shared by every configuration-driven crawler.

The helpers only ever receive selectors from ``MarketplaceConfig``; they hold
no marketplace knowledge of their own.
"""

import logging
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import urlparse

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError


class _HtmlText(HTMLParser):
    """Convert configured HTML content to plain text without script/style content."""

    def __init__(self, value: str) -> None:
        super().__init__()
        self._ignored = 0
        self._parts: list[str] = []
        self.feed(value)
        self.text = " ".join("".join(self._parts).split()) or None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in {"script", "style"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self._parts.append(data)


class PageHelpers:
    """Mixin with tolerant locator queries over an injected Playwright page.

    Subclasses must set ``self.page`` and ``self.logger``.
    """

    page: Page
    logger: logging.Logger
    NAVIGATION_TIMEOUT_MS = 30_000

    @staticmethod
    def _is_navigable_http_url(url: str) -> bool:
        """Return whether a resolved URL can safely be opened by Playwright."""
        parsed = urlparse(url)
        return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _selector_alternatives(selector: Optional[str]) -> list[str]:
        """Return non-empty CSS selector alternatives in configuration order."""
        if not selector:
            return []
        return [candidate.strip() for candidate in selector.split(",") if candidate.strip()]

    async def _goto_dom_ready(self, url: str) -> None:
        """Navigate until the DOM is ready, tolerating only navigation timeouts."""
        self.logger.info("page navigation starts url=%s", url)
        try:
            await self.page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.NAVIGATION_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            self.logger.warning(
                "Navigation timed out after DOM-ready wait; continuing extraction: %s",
                url,
            )
        self.logger.info("page navigation completes url=%s", url)

    async def _optional_text(self, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        return await self._optional_text_from(self.page, selector)

    async def _optional_text_from(self, owner: Any, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        locator = owner.locator(selector).first
        if await locator.count() == 0:
            return None
        value = (await locator.inner_text()).strip()
        return value or None

    async def _optional_attribute_from(
        self, owner: Any, selector: Optional[str], attribute: str
    ) -> Optional[str]:
        if not selector:
            return None
        locator = owner.locator(selector).first
        if await locator.count() == 0:
            return None
        return await locator.get_attribute(attribute)

    async def _optional_html_text(self, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        locator = self.page.locator(selector).first
        if await locator.count() == 0:
            return None
        if hasattr(locator, "inner_html"):
            return _HtmlText(await locator.inner_html()).text
        return (await locator.inner_text()).strip() or None

    async def _all_text(self, selector: Optional[str]) -> list[str]:
        if not selector:
            return []
        return [
            value
            for value in [
                (await item.inner_text()).strip()
                for item in await self.page.locator(selector).all()
            ]
            if value
        ]
