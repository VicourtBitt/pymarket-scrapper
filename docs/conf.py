"""Sphinx configuration for PyMarket-Scrapper."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

project = "PyMarket-Scrapper"
author = "PyMarket-Scrapper contributors"
release = "0.1"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
]
autosummary_generate = True
autodoc_mock_imports = ["playwright"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_theme = "alabaster"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_theme_options = {
    "page_width": "1120px",
    "sidebar_width": "280px",
    "fixed_sidebar": True,
}
