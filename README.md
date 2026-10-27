# PyMarket-Scrapper
This is a POC (Proof-Of-Concept) for a Python module that the solely objective is to make easier to setup automations such data extraction using WebScrapping but in a agnostic way.
The fundamental part of turning the data extraction easier relies on isolating the layers and responsibilities of each code section, making the pipeline accept any kind of information because the output will be transformed.

# pymarket-scrapper
A modular template for marketplace web scraping with support for platforms like Amazon and Mercado Livre. Provides reusable scraper components, database models, and a scalable foundation for collecting, storing, and analyzing marketplace data.

## Marketplace configuration

Marketplace definitions are loaded by key from an explicitly supplied directory:

```python
from pathlib import Path
from models.config import MarketplaceConfig

config = MarketplaceConfig.from_marketplace("amazon", Path("configs"))
```

The canonical filename is `configs/<marketplace>.yml`. The application accepts
`MARKETPLACE` and `MARKETPLACE_CONFIG_DIR` environment variables; the latter
defaults to `configs` only at the application boundary. Selectors, URL, and
query/sort parameter names are read from the validated configuration.

## Build the documentation

Install the documentation dependency and build the local HTML site from the
repository root:

```bash
python -m pip install -r requirements.txt
python -m sphinx -W -b html docs docs/_build/html
```

Open `docs/_build/html/index.html` to view the generated documentation. The
build imports the project modules but does not launch a browser, access the
network, or connect to a database.
