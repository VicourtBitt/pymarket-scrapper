"""Load and validate marketplace configuration files."""

from pathlib import Path
import re
from typing import Any, Dict

import yaml
from pydantic import ValidationError

from models.config import MarketplaceConfig


class ConfigReaderError(ValueError):
    """Base class for errors raised while reading marketplace configuration."""


class ConfigFileError(ConfigReaderError):
    """Raised when the configuration path cannot be read."""


class ConfigParseError(ConfigReaderError):
    """Raised when the configuration is not valid YAML."""


class ConfigValidationError(ConfigReaderError):
    """Raised when valid YAML does not satisfy the configuration schema."""


class MarketplaceConfigFactory:
    """Resolve marketplace names to configuration files without a hidden path."""

    @staticmethod
    def from_marketplace(
        marketplace: str, configs_dir: Path
    ) -> MarketplaceConfig:
        if not isinstance(marketplace, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]*", marketplace
        ):
            raise ConfigFileError(
                "Invalid marketplace key; use only letters, numbers, '_' or '-'."
            )
        # Resolve both sides before opening the file.  This also protects the
        # loader when ``configs_dir`` contains symlinks.
        root: Path = Path(configs_dir).expanduser().resolve()
        path: Path = (root / f"{marketplace}.yml").resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ConfigFileError(
                "Marketplace configuration must be inside the configured directory"
            ) from exc
        return MarketplaceConfigReader(path).read()


class MarketplaceConfigReader:
    """Read a marketplace configuration from an explicitly supplied YAML path.

    The reader deliberately does not provide a default path. This keeps the
    choice of marketplace and configuration file with the caller.
    """

    def __init__(self, path: Path) -> None:
        self.path: Path = path

    def read(self) -> MarketplaceConfig:
        """Read, safely parse, and validate the configured YAML file."""
        if not self.path.exists():
            raise ConfigFileError(
                f"Marketplace configuration does not exist: {self.path}"
            )
        if not self.path.is_file():
            raise ConfigFileError(
                f"Marketplace configuration path is not a file: {self.path}"
            )

        try:
            content: str = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ConfigFileError(
                f"Unable to read marketplace configuration '{self.path}': {exc}"
            ) from exc

        try:
            raw_config: Any = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise ConfigParseError(
                f"Invalid YAML in marketplace configuration '{self.path}': {exc}"
            ) from exc

        if not isinstance(raw_config, dict):
            raise ConfigValidationError(
                f"Marketplace configuration '{self.path}' must contain a YAML mapping"
            )

        config_data: Dict[str, Any] = raw_config
        try:
            return MarketplaceConfig.model_validate(config_data)
        except ValidationError as exc:
            raise ConfigValidationError(
                f"Marketplace configuration '{self.path}' failed schema validation: "
                f"{exc}"
            ) from exc
