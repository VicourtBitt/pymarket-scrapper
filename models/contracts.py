"""Small Pydantic contracts for extraction run input, not database tables."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ExtractionRunRequest(BaseModel):
    """Validated input needed to start an extraction run."""

    marketplace: str = Field(min_length=1, max_length=100)
    requested_by: Optional[str] = Field(default=None, max_length=255)
    source: Optional[str] = Field(default=None, max_length=255)
    config_hash: Optional[str] = Field(default=None, max_length=128)
    metadata: Dict[str, Any] = Field(default_factory=dict)
