from typing import AsyncIterator, TypeVar, Generic
from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)


class Deduplicator(Generic[T]):
    """
    Middleware that intercepts an async stream and drops items
    if their specified key_field has already been seen.
    """

    def __init__(self, key_field: str) -> None:
        self.seen = set()
        self.key_field = key_field

    async def process(self, stream: AsyncIterator[T]) -> AsyncIterator[T]:
        async for item in stream:
            # Dynamically get the ID (e.g., product_id or vendor_id)
            key = getattr(item, self.key_field, None)

            if key and key not in self.seen:
                self.seen.add(key)
                yield item  # Pass it down the pipeline
            elif not key:
                # If there's no key, we can't deduplicate it, so we let it pass
                yield item