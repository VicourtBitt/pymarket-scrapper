from pathlib import Path

import pytest

from models.config_reader import (
    ConfigFileError,
    ConfigParseError,
    ConfigValidationError,
    MarketplaceConfigReader,
    MarketplaceConfigFactory,
)


VALID_CONFIG = """
query_parameters:
  search_key: q
  sort_key: sort
  sort_values:
    best_sellers: best
search_page:
  product_card: ".product"
  sponsored_ad_tag: ".sponsored"
  title: ".title"
  url: "a"
  price: ".price"
  id_attribute: "data-id"
  next_page_button: ".next"
vendor_page:
  name: ".vendor-name"
"""


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "marketplace.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_reads_valid_yaml(tmp_path: Path) -> None:
    config = MarketplaceConfigReader(write_config(tmp_path, VALID_CONFIG)).read()

    assert config.query_parameters.search_key == "q"
    assert config.search_page.product_card == ".product"
    assert config.vendor_page.name == ".vendor-name"


def test_missing_path_raises_config_file_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileError, match="does not exist"):
        MarketplaceConfigReader(tmp_path / "missing.yaml").read()


def test_directory_path_raises_config_file_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigFileError, match="not a file"):
        MarketplaceConfigReader(tmp_path).read()


def test_malformed_yaml_raises_config_parse_error(tmp_path: Path) -> None:
    path = write_config(tmp_path, "query_parameters: [")

    with pytest.raises(ConfigParseError, match="Invalid YAML"):
        MarketplaceConfigReader(path).read()


def test_schema_failure_raises_config_validation_error(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
query_parameters:
  search_key: q
""",
    )

    with pytest.raises(ConfigValidationError, match="schema validation"):
        MarketplaceConfigReader(path).read()


def test_loads_marketplace_by_key_from_yml_directory(tmp_path: Path) -> None:
    (tmp_path / "amazon.yml").write_text(VALID_CONFIG, encoding="utf-8")

    config = MarketplaceConfigFactory.from_marketplace("amazon", tmp_path)

    assert config.query_parameters.search_key == "q"


def test_marketplace_loader_requires_canonical_yml_file(tmp_path: Path) -> None:
    (tmp_path / "amazon.yaml").write_text(VALID_CONFIG, encoding="utf-8")

    with pytest.raises(ConfigFileError, match="does not exist"):
        MarketplaceConfigFactory.from_marketplace("amazon", tmp_path)


@pytest.mark.parametrize("marketplace", ["../amazon", "amazon/secret", "", "a.b"])
def test_marketplace_loader_rejects_path_traversal_or_unsafe_keys(
    tmp_path: Path, marketplace: str
) -> None:
    with pytest.raises(ConfigFileError, match="Invalid marketplace key"):
        MarketplaceConfigFactory.from_marketplace(marketplace, tmp_path)


def test_marketplace_loader_rejects_config_symlink_outside_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "amazon.yml").write_text(VALID_CONFIG, encoding="utf-8")
    link = tmp_path / "configs"
    link.mkdir()
    try:
        (link / "amazon.yml").symlink_to(outside / "amazon.yml")
    except OSError:
        pytest.skip("symbolic links are not supported on this platform")

    with pytest.raises(ConfigFileError, match="inside the configured directory"):
        MarketplaceConfigFactory.from_marketplace("amazon", link)
