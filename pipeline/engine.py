from typing import Any, AsyncIterator, List


class Pipeline:
    """Pipe an async stream through bounded processing stages and a sink."""

    def __init__(self) -> None:
        self.steps: List[Any] = []
        self.sink: Any = None

    def add_step(self, step: Any) -> "Pipeline":
        self.steps.append(step)
        return self

    def set_sink(self, sink: Any) -> "Pipeline":
        self.sink = sink
        return self

    async def run(self, stream: AsyncIterator[Any]) -> None:
        current: AsyncIterator[Any] = stream
        for step in self.steps:
            current = step.process(current)
        if self.sink is None:
            async for _ in current:
                pass
            return
        async for item in current:
            self.sink.load_product(item.model_dump())
