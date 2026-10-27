Architecture and workflow
==========================

The project separates extraction, transformation, and loading:

#. ``MarketplaceConfig`` loads selectors, URLs, and query parameters from YAML.
#. A crawler yields ``ProductItem`` models through an asynchronous iterator.
#. ``main.run_amazon_workflow`` enriches each search product from its detail
   page and resolves each vendor once using a per-run cache.
#. ``Pipeline`` applies ``Deduplicator`` and ``SQLFilter`` stages in order.
#. ``PostgreSQLSink`` upserts the filtered products and resolved vendors.
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
