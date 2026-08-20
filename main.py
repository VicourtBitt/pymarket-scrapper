# Complete, well-commented, runnable code for this single file
import asyncio
from playwright.async_api import async_playwright
from crawlers import AmazonCrawler, AmazonSortFilter
from include import LocalizedSanitization
from pipeline import Deduplicator, SQLFilter, RegexExtractor, PostgreSQLSink
from models import ProductItem

async def main():
    # --- Framework Setup Phase ---
    db_url = "postgresql://pymarket_scrapper:cHltYXJrZXRfc2NyYXBwZXI@localhost:5432/pymarket_data"

    def erp_matcher(vendor_data: dict) -> str:
        vendor_name = vendor_data.get('name', '').lower()
        if 'official' in vendor_name:
            return f"ERP_PARTNER_{vendor_data['vendor_id']}"
        return None

    db_sink = PostgreSQLSink(connection_url=db_url, identity_resolver=erp_matcher)

    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        us_sanitizer = LocalizedSanitization(decimal_separator=",", thousands_separator=".")
        crawler = AmazonCrawler(page, sanitizer=us_sanitizer, base_url="https://www.amazon.com.br")

        print("-" * 40)

        product_deduplicator = Deduplicator[ProductItem](key_field="product_id")
        sql_filter = SQLFilter[ProductItem](
            model_class=ProductItem,
            where_clause="title ILIKE '%Semente%'"
        )

        search_query = "sementes para plantar"
        raw_stream = crawler.extract_search_items(
            search_query,
            limit=50,
            sort_filter=AmazonSortFilter.RELEVANCE
        )
        dedup_stream = product_deduplicator.process(raw_stream)
        filtered_stream = sql_filter.process(dedup_stream, batch_size=10)

        print(f"🚀 Starting ETL Pipeline for: '{search_query}'")

        async for product in filtered_stream:
            print(f"✅ VALID PRODUCT: {product.title[:50]}... | Price: ${product.price}")

            try:
                db_sink.load_product(product.model_dump())
                print(f"   -> Product '{product.product_id}' upserted successfully.")
            except Exception as e:
                print(f"   -> ❌ Failed to load product: {e}")

            print("-" * 40)

        print("Closing browser...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())