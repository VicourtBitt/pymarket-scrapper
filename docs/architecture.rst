Architecture and workflow
==========================

The project separates extraction, transformation, and loading:

#. ``MarketplaceConfig`` loads selectors, URLs, query parameters, locale and
   browser settings from YAML; ``crawlers.registry`` picks the crawler pair.
#. A ``BaseCrawler`` yields search ``ProductItem`` models through an
   asynchronous iterator and fetches product detail pages. A separate
   ``BaseVendorCrawler`` extracts seller profiles and storefront catalogs.
#. ``pipeline.workflow.ExtractionWorkflow`` composes ``Pipeline`` stages
   (title filter, ``Deduplicator``, detail enrichment, ``SQLFilter``) for the
   selected mode, resolving each vendor once through ``VendorResolver``.
#. ``PostgreSQLSink`` upserts products and vendors, and records the job as an
   extraction run with one search and its product observations.
#. Resolved vendor storefronts are scanned afterward and their catalog products
   are upserted without recursively re-entering the search workflow.

Streaming contract
------------------

Crawler and stage interfaces use asynchronous iterators. This keeps extraction
and filtering incremental: a stage consumes the previous stream and yields the
next stream instead of requiring the complete result set in memory. The SQL
filter batches records in an in-memory DuckDB connection and flushes its final
partial batch when the input ends.

Configuration boundary
----------------------

Selectors and sort values belong in ``configs/*.yml``. Crawler implementations
consume the validated Pydantic configuration and do not define marketplace
selectors in Python. This keeps the crawler reusable across configuration
variants and makes selector changes deployable without changing extraction
logic.
