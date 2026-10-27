Setup
=====

Install the project dependencies from the repository root::

   python -m pip install -r requirements.txt

The Amazon workflow reads marketplace configuration from ``configs/`` by
default. Set ``DATABASE_URL`` before running ``main.py``. A live run also
requires Playwright's browser binaries, but the documentation build does not
open a browser or connect to a database.

Configuration
-------------

Marketplace configuration is loaded with
``MarketplaceConfig.from_marketplace(name, config_directory)``. The canonical
file name is ``configs/<marketplace>.yml``. The application boundary accepts
these environment variables:

* ``MARKETPLACE``: marketplace key, defaulting to ``amazon``.
* ``MARKETPLACE_CONFIG_DIR``: configuration directory, defaulting to
  ``configs``.
* ``DATABASE_URL``: SQLAlchemy connection URL required by the workflow.
* ``PRODUCT_TITLE_CONTAINS``: optional title filter value.

Build the documentation
-----------------------

From the repository root, install Sphinx if it is not already available and
build the HTML site::

   python -m pip install Sphinx
   python -m sphinx -W -b html docs docs/_build/html

Open ``docs/_build/html/index.html`` in a browser to view the generated site.
