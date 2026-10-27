"""Application environment loading."""

from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_environment(dotenv_path: Optional[Path] = None) -> None:
    """Load local environment values without overriding explicit env vars."""
    load_dotenv(
        dotenv_path=dotenv_path or PROJECT_ROOT / ".env",
        override=False,
    )
