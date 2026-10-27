"""Manually test extraction from product URLs stored in the database.

Usage:
    ./venv/bin/python scripts/test_live_amazon_product.py --limit 10
    ./venv/bin/python scripts/test_live_amazon_product.py --run-id RUN_ID
    ./venv/bin/python scripts/test_live_amazon_product.py --all
"""

import asyncio
import argparse
import json
import os
from typing import Any

from playwright.async_api import async_playwright

from live_amazon_common import create_crawler, PROJECT_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract product details for URLs stored in the database."
    )
    parser.add_argument("--run-id", help="Only products observed in this extraction run.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Use products from all extraction runs instead of the latest run.",
    )
    parser.add_argument("--product-id", help="Restrict extraction to one product ID.")
    parser.add_argument("--title-contains", help="Restrict extraction by product title.")
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


def product_urls(args: argparse.Namespace) -> list[tuple[str, str]]:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from models.database import (
        ExtractionRun,
        ExtractionSearch,
        ProductObservation,
        ProductRecord,
    )

    if args.limit < 1:
        raise ValueError("--limit must be greater than zero")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set in the environment or .env")

    marketplace = os.getenv("MARKETPLACE", "amazon")
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            run_id = args.run_id
            if not run_id and not args.all:
                run_id = session.scalar(
                    select(ExtractionRun.run_id)
                    .where(ExtractionRun.marketplace == marketplace)
                    .order_by(ExtractionRun.started_at.desc())
                    .limit(1)
                )
                if not run_id:
                    raise RuntimeError(
                        f"No extraction runs found for marketplace '{marketplace}'"
                    )

            statement = (
                select(ProductRecord.product_id, ProductRecord.url)
                .where(
                    ProductRecord.marketplace == marketplace,
                    ProductRecord.url.is_not(None),
                )
                .order_by(ProductRecord.updated_at.desc())
                .limit(args.limit)
            )
            if args.product_id:
                statement = statement.where(ProductRecord.product_id == args.product_id)
            if args.title_contains:
                statement = statement.where(
                    ProductRecord.title.ilike(f"%{args.title_contains}%")
                )
            if run_id:
                statement = (
                    statement.join(
                        ProductObservation,
                        ProductObservation.product_id == ProductRecord.product_id,
                    )
                    .join(
                        ExtractionSearch,
                        ExtractionSearch.search_id == ProductObservation.search_id,
                    )
                    .where(ExtractionSearch.run_id == run_id)
                    .distinct()
                )

            return [
                (product_id, url)
                for product_id, url in session.execute(statement)
                if url
            ]
    finally:
        engine.dispose()


async def main() -> None:
    from include import load_environment

    load_environment(PROJECT_ROOT / ".env")
    args = parse_args()
    urls = product_urls(args)
    if not urls:
        print("No matching product URLs found.")
        return

    async with async_playwright() as playwright:
        browser, _, crawler = await create_crawler(playwright)
        try:
            for product_id, url in urls:
                try:
                    result: dict[str, Any] = await crawler.extract_product_info(url)
                    print(json.dumps(
                        {
                            "product_id": product_id,
                            "status": "success",
                            "result": result,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ))
                except Exception as exc:
                    print(json.dumps(
                        {
                            "product_id": product_id,
                            "status": "error",
                            "url": url,
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    ))
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
