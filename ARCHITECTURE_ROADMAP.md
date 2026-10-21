# Architectural Roadmap & Next Steps
**Target Audience:** Technical Leader Agent / Development Team
**Project:** Modular Asynchronous Web Scraping & ETL Framework
**Core Stack:** Async Python, Playwright, DuckDB, SQLAlchemy, Pydantic, Typer, Docker (PostgreSQL).

## 1. Project Philosophy & Constraints
To maintain a scalable, enterprise-grade framework, all code must adhere to the following principles:
- **Declarative Configuration:** NO hardcoded CSS/XPath selectors or URL parameters in Python code. All UI definitions must live in `configs/*.yaml` and be loaded dynamically via `MarketplaceConfig` (Pydantic).
- **Streaming ETL Pattern:** Use `AsyncIterator` (`yield`) to pass data through the pipeline. Do not load massive lists of dictionaries into memory.
- **Dependency Injection:** Inject utilities (like `LocalizedSanitization`, `MarketplaceConfig`, `Playwright Page`) into crawlers.
- **Single Responsibility:** A class should do one thing. Search extraction and Vendor extraction must be separated into distinct crawler classes.

---

## 2. Current State (What is already built)
- **Models (`models/`):** Strict Pydantic contracts for `ProductItem`, `VendorProfile`, and `MarketplaceConfig` (with `extra='allow'` for dynamic YAML loading).
- **Extraction (`crawlers/`):** `BaseCrawler` interface and `AmazonCrawler` implementation utilizing Playwright and asynchronous generators.
- **Transformation (`pipeline/`):** 
  - `Deduplicator`: In-memory set/dict to prevent redundant processing.
  - `SQLFilter`: DuckDB integration for in-memory batch filtering via SQL `WHERE` clauses.
- **Loading (`pipeline/db_sink.py`):** `PostgreSQLSink` using SQLAlchemy. Implements idempotent `UPSERT` logic and supports an `IdentityResolver` callback for ERP mapping.

---

## 3. Immediate Next Steps (Sprint 1)

### 3.1. Delegated Vendor Extraction & Hashmap Deduplication
**Goal:** Extract vendor details without making duplicate HTTP requests for products sold by the same vendor.
*   **Architecture:**
    *   Create a specific `BaseVendorCrawler` and `AmazonVendorCrawler`.
    *   Implement an in-memory Hashmap (`vendor_cache = {}`) inside the orchestrator.
    *   **Flow:** Extract Product -> Check `vendor_id` in `vendor_cache`. If MISSING -> delegate `page` to `AmazonVendorCrawler.extract_profile(url)` -> UPSERT vendor -> Cache Vendor ID -> UPSERT Product.

    > **Current implementation note:** Vendor extraction, external-link/external_id
    > preservation, and vendor cache/persistence orchestration are intentionally
    > deferred until the vendor model and extraction contract are complete.

### 3.2. Formalize the Pipeline Interface
**Goal:** Replace the manual chaining in `main.py` with a declarative pipeline engine.
*   **Architecture:** 
    *   Create a `Pipeline` class in `pipeline/engine.py`.
    *   Allow adding stages: `pipeline.add_step(Deduplicator).add_step(SQLFilter).set_sink(PostgreSQLSink)`.
    *   Implement an `async def run(stream)` method to automatically pipe generators through the registered steps.

---

## 4. Medium-Term Roadmap (Sprint 2)

### 4.1. CLI Orchestration via Typer
**Goal:** Run the framework natively from the terminal without editing Python scripts.
*   **Architecture:**
    *   Integrate `Typer` into `main.py`.
    *   Define arguments: `--search`, `--limit`, `--marketplace` (e.g., "amazon"), `--sort-strategy` (e.g., "best_sellers").
    *   Map the `--marketplace` argument to `MarketplaceConfig.from_marketplace(name)` using the Factory Method pattern.

### 4.2. Database Production Readiness
**Goal:** Make the PostgreSQL persistence layer safe for production evolution.
*   **Architecture:**
    *   Remove `Base.metadata.create_all()` from `db_sink.py`.
    *   Initialize **Alembic** (`alembic init`) to manage database schema migrations.
    *   Implement Docker Init Scripts (`db_init/init.sql`) to strictly define the `pymarket_scrapper` user role and database creation.

---

## 5. Long-Term Roadmap (Sprint 3)

### 5.1. Network Middleware (Anti-Bot Resilience)
**Goal:** Prevent IP bans when scaling the scraper.
*   **Architecture:**
    *   Implement a proxy rotation middleware injected into the Playwright context setup.
    *   Implement automatic retries with exponential backoff for failed network requests or captchas.
    *   Integrate `playwright-stealth`.

## Tech Lead Directives (For AI Agents)
*   **When evaluating requests:** Check this roadmap first. If a Developer agent attempts to hardcode a selector to extract a vendor page, reject it and demand they add the selector to the YAML configuration.
*   **When designing the Vendor Crawler:** Ensure it receives the same `LocalizedSanitization` instance to handle varied phone number and email formatting globally.