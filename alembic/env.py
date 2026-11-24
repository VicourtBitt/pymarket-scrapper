"""Alembic environment for the SQLAlchemy declarative metadata.

Database credentials are read from the process environment (or the local
``.env`` file when running Alembic directly).  They are deliberately never
written to logs or included in configuration errors.
"""

from configparser import ConfigParser
from logging.config import fileConfig
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import engine_from_config, pool

from include import load_environment
from models.database import Base

config = context.config
load_environment()


def _configuration_value(name: str) -> Optional[str]:
    """Return a non-empty environment value."""
    value: Optional[str] = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _database_url() -> str:
    """Resolve a SQLAlchemy URL without logging credentials."""
    explicit_url: Optional[str] = _configuration_value("DATABASE_URL")
    if explicit_url:
        return explicit_url

    user: Optional[str] = _configuration_value("DB_USER")
    password: Optional[str] = _configuration_value("DB_PASS")
    database: Optional[str] = _configuration_value("DB_NAME")
    if user and password and database:
        return (
            "postgresql+psycopg2://"
            f"{quote_plus(user)}:{quote_plus(password)}@localhost:5432/"
            f"{quote_plus(database)}"
        )

    configured_url: str = config.get_main_option("sqlalchemy.url", "").strip()
    if configured_url and configured_url != "postgresql+psycopg2://":
        return configured_url
    raise RuntimeError(
        "Database configuration is missing; set DATABASE_URL or "
        "DB_USER, DB_PASS, and DB_NAME."
    )


def _configure_alembic_logging() -> None:
    """Use INI logging only when all sections required by ``fileConfig`` exist."""
    filename: Optional[str] = config.config_file_name
    if not filename:
        return
    parser = ConfigParser()
    try:
        parser.read(filename, encoding="utf-8")
    except (OSError, UnicodeError):
        return
    required_sections = {"formatters", "handlers", "loggers"}
    if required_sections.issubset(parser.sections()):
        fileConfig(filename)


_configure_alembic_logging()

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    url: str = _database_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a configured SQLAlchemy engine."""
    configuration: dict[str, Any] = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
