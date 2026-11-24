from collections.abc import AsyncIterator
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)


class Deduplicator(Generic[T]):
    """Drop repeated keyed models while preserving unkeyed models."""

    def __init__(self, key_field: str) -> None:
        self.seen = set()
        self.key_field = key_field

    async def process(self, stream: AsyncIterator[T]) -> AsyncIterator[T]:
        """Yield the first item for each non-empty configured key.

        Args:
            stream: Asynchronous model stream to inspect.

        Yields:
            The first model for each key, plus models without a key.
        """
        async for item in stream:
            # Dynamically get the ID (e.g., product_id or vendor_id)
            key = getattr(item, self.key_field, None)

            if key and key not in self.seen:
                self.seen.add(key)
                yield item  # Pass it down the pipeline
            elif not key:
                # If there's no key, we can't deduplicate it, so we let it pass
                yield item