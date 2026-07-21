# Complete, well-commented, runnable code for this single file
import asyncio
from playwright.async_api import async_playwright
from crawlers import AmazonCrawler
from include import LocalizedSanitization
from pipeline import Deduplicator, SQLFilter, RegexExtractor
from models import ProductItem


async def main():
    # 1. Start Playwright
    async with async_playwright() as p:
        print("Launching browser...")
        # headless=False lets you watch the browser move!
        # Change to True when you want it to run silently in the background.
        browser = await p.chromium.launch(headless=False)

        # 2. Create a new browser context (like a fresh incognito window)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        )

        # 3. Open a new tab
        page = await context.new_page()

        # 4. Initialize our framework's crawler with the Playwright tab and the Sanitizer
        # We configure it for US format (Amazon.com).
        # If scraping Amazon.com.br, we'd use: LocalizedSanitization(decimal_separator=",", thousands_separator=".")
        br_sanitizer = LocalizedSanitization(decimal_separator=",", thousands_separator=".")
        crawler = AmazonCrawler(page, sanitizer=br_sanitizer, base_url="https://www.amazon.com.br")

        print("-" * 40)

        # 5. Initialize our Phase 2 Middlewares!
        # We want to drop duplicate products and filter out cheap/renewed items.
        product_deduplicator = Deduplicator[ProductItem](key_field="product_id")
        sql_filter = SQLFilter[ProductItem](
            model_class=ProductItem,
            where_clause="price > 20 AND title NOT ILIKE '%espalhador%'"
        )

        # 6. Chain the Async Generators (The Pipeline)
        search_query = "isla sementes"

        # Raw stream from Amazon
        raw_stream = crawler.extract_search_items(search_query, limit=15)

        # Pass the raw stream through the deduplicator
        dedup_stream = product_deduplicator.process(raw_stream)

        # Pass the deduplicated stream through the SQL filter (processed in batches)
        filtered_stream = sql_filter.process(dedup_stream, batch_size=10)

        # 7. Consume the Pipeline
        print(f"🚀 Starting ETL Pipeline for: '{search_query}'")
        async for product in filtered_stream:
            print(f"✅ VALID PRODUCT: {product.title[:50]}... | Price: ${product.price}")
            print("-" * 40)

        # 8. Cleanup
        print("Closing browser...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())