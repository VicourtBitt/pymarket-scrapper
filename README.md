# PyMarket-Scrapper

PyMarket-Scrapper is a proof-of-concept, configuration-driven framework for
marketplace web scraping and ETL. It separates extraction, transformation, and
loading so marketplace-specific crawlers can stream typed product records into
reusable pipeline stages and a database sink. The current executable workflow
is Amazon-focused and is not presented as production-ready.

## Capabilities

- Async Playwright extraction for Amazon search results, product details,
  vendors, and vendor catalogs.
- YAML configuration for marketplace URLs, selectors, and sort values.
- Pydantic models for extracted product and vendor data.
- Streaming async pipeline stages for deduplication and DuckDB-backed SQL
  filtering.
- SQLAlchemy persistence with PostgreSQL upserts through `PostgreSQLSink`.
- An Alembic revision for extraction runs, searches, products, vendors, and
  product observations.
- Sphinx API and architecture documentation under `docs/`.

Mercado Livre and the standalone vendor crawler interfaces are placeholders;
they do not provide a complete live workflow yet.

## Architecture and workflow

The current Amazon flow is:

1. Load and validate `configs/<marketplace>.yml`.
2. Stream search results from `AmazonCrawler`.
3. Fetch product details and resolve each vendor once per run using an
   in-memory cache.
4. Apply `Deduplicator` and `SQLFilter` through `Pipeline`.
5. Upsert filtered products and resolved vendors with `PostgreSQLSink`.
6. Optionally scan resolved vendor storefronts and upsert unique catalog products.

The crawler and pipeline stages use async iterators, so the complete result set
does not need to be held in memory. See the [architecture guide](docs/architecture.rst)
and [API reference](docs/api.rst) for the module-level details.

## Repository layout

| Path | Purpose |
| --- | --- |
| `main.py` | Application wiring and the executable Amazon workflow |
| `crawlers/` | Marketplace and vendor crawler interfaces and implementations |
| `pipeline/` | Async pipeline stages and the PostgreSQL sink |
| `models/` | Pydantic contracts, configuration loading, and SQLAlchemy models |
| `configs/` | Marketplace YAML configuration, including Amazon selectors |
| `alembic/` | Database migration configuration and revisions |
| `tests/` | Unit and workflow tests |
| `docs/` | Sphinx setup, architecture, setup, and API documentation |

## Prerequisites

- Python 3.10 or newer.
- A PostgreSQL database reachable through a SQLAlchemy connection URL for a
  live run.
- Chromium browser binaries for Playwright. The Sphinx build and unit tests do
  not require a live browser, network access, or a database connection.

## Installation

From the repository root, create an environment and install the pinned project
dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

On a system where Playwright reports missing operating-system libraries, use
the platform-specific browser dependency instructions from Playwright.

## Configuration

The canonical marketplace configuration filename is
`configs/<marketplace>.yml`. Selectors, the base URL, and query/sort parameter
names belong in YAML rather than crawler code:

```python
from pathlib import Path
from models.config import MarketplaceConfig

config = MarketplaceConfig.from_marketplace("amazon", Path("configs"))
```

The application loads a local `.env` file when present and does not override
environment variables that are already set.

| Variable | Default | Description |
| --- | --- | --- |
| `MARKETPLACE` | `amazon` | Marketplace key used to select the YAML file |
| `MARKETPLACE_CONFIG_DIR` | `configs` | Directory containing marketplace YAML files |
| `DATABASE_URL` | none | Required SQLAlchemy connection URL |
| `PRODUCT_TITLE_CONTAINS` | none | Optional case-insensitive title substring. Product and vendor/all detail workflows filter search results before opening product pages; product-only search results are preserved. |
| `LOG_DIRECTORY` | `logs` | Directory used by application logging |
| `LOG_LEVEL` | `INFO` | Python logging level used by the CLI, such as `DEBUG`, `INFO`, or `WARNING` |

The current `main.py` workflow uses the search term `sementes para plantar`,
requests up to 50 results, and opens Chromium with `headless=False`.

### Diagnostic logs

The CLI configures the `pymarket_scrapper` logger and writes normal output and
rotating diagnostic files under `LOG_DIRECTORY` (default: `logs`). Set the
standard `LOG_LEVEL` environment variable when a more or less detailed run is
needed, for example:

```bash
LOG_LEVEL=DEBUG LOG_DIRECTORY=logs python main.py \
  --extraction vendor --search "garden seeds" --headless
```

Vendor and product detail stage messages identify navigation, selector
inspection, extracted-field presence, normalization, and persistence. Sensitive
seller values such as CNPJ, phone numbers, and email addresses are intentionally
not written to the logs; marketplace page URLs may be included to identify the
page where processing stopped.

## Database and migrations

The persistence layer targets PostgreSQL through SQLAlchemy. Apply the checked-in
Alembic revision after setting `DATABASE_URL` (or `DB_USER`, `DB_PASS`, and
`DB_NAME`) in the environment:

```bash
alembic upgrade head
```

The initial revision creates vendor, product, extraction-run, extraction-search,
and product-observation tables. Review `alembic.ini` and `alembic/env.py` for
the repository's migration connection behavior before running it against a
shared database.

## Run the application

The executable is a Typer CLI. Set a SQLAlchemy PostgreSQL URL (or pass
`--database-url`) and execute it from the repository root:

```bash
export DATABASE_URL='postgresql+psycopg2://user:password@localhost:5432/database'
python main.py --search "sementes para plantar" --limit 50 --headless
```

This command performs live marketplace requests and writes data to the
configured database. The default `product` extraction persists deduplicated
search products without opening product or vendor detail pages. Use
`--extraction vendor` to persist only vendors,
or `--extraction all` to additionally crawl storefront catalog products.
`--storefront-products` enables catalog processing for vendor/all modes and is
ignored by product mode, and
`--recursive-vendors` backfills persisted products whose `vendor_id` is NULL.
Other options include `--marketplace`, `--sort-strategy`, `--limit`,
`--product-title-contains`, and `--no-headless`. The title filter defaults to
`PRODUCT_TITLE_CONTAINS`; an explicitly supplied CLI value takes precedence,
and an empty or whitespace-only value disables filtering.

```bash
python main.py --extraction all --search "garden seeds" --storefront-products
python main.py --recursive-vendors --database-url "$DATABASE_URL"
```

Unit tests can import `main.app` and workflow helpers without launching a
browser or connecting to a database.

## Test

Run the test suite from the repository root:

```bash
python -m pytest
```

The tests include crawler, configuration, pipeline, persistence, logging, and
workflow coverage. Live marketplace scripts under `scripts/` may require
network access and browser setup; they are separate from the standard test
suite.

## Build the documentation

Build the local Sphinx HTML site with warnings treated as errors:

```bash
python -m sphinx -W -b html docs docs/_build/html
```

Open `docs/_build/html/index.html` to view it. The documentation build imports
project modules but does not launch a browser, access the network, or connect
to a database. The detailed guides are [Setup](docs/setup.rst),
[Architecture](docs/architecture.rst), and [API](docs/api.rst).

## Current status and limitations

This repository is an evolving POC. The Amazon path is the most complete live
workflow, while Mercado Livre extraction, the standalone vendor crawler, a
general CLI, and production hardening remain incomplete or planned. The
roadmap also calls out future retry/anti-bot middleware and further persistence
lifecycle integration. Marketplace selectors can change independently of this
codebase, so live extraction may require YAML updates.
