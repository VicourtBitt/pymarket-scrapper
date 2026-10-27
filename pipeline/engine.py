from collections.abc import AsyncIterator
from typing import Any, List


class Pipeline:
    """Pipe an async stream through ordered stages and an optional sink."""

    def __init__(self) -> None:
        self.steps: List[Any] = []
        self.sink: Any = None

    def add_step(self, step: Any) -> "Pipeline":
        """Append a stage and return this pipeline for fluent configuration."""
        self.steps.append(step)
        return self

    def set_sink(self, sink: Any) -> "Pipeline":
        """Set the object that receives each final model as a dictionary."""
        self.sink = sink
        return self

    async def run(self, stream: AsyncIterator[Any]) -> None:
        """Consume ``stream`` through every stage and persist final items.

        Args:
            stream: Asynchronous source consumed exactly once.

        Side Effects:
            Calls each stage's ``process`` method and, when configured, calls
            the sink's ``load_product`` method for every final item.
        """
        current: AsyncIterator[Any] = stream
        for step in self.steps:
            current = step.process(current)
        if self.sink is None:
            async for _ in current:
                pass
            return
        async for item in current:
            self.sink.load_product(item.model_dump())
