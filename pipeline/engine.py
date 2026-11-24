"""Declarative streaming pipeline: ``source -> stages... -> sink``."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Generic, Optional, Protocol, TypeVar, Union, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class Stage(Protocol):
    """A transformation over a model stream (filter, enrich, deduplicate...)."""

    def process(self, stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
        ...


class ProductSink(Protocol):
    """Anything that can persist one product dictionary."""

    def load_product(self, product_data: dict[str, Any]) -> None:
        ...


StreamTransform = Callable[[AsyncIterator[Any]], AsyncIterator[Any]]
StepLike = Union[Stage, StreamTransform]


@dataclass
class PipelineStats:
    """Item counts observed by one ``Pipeline.run`` call."""

    extracted: int = 0
    loaded: int = 0


class Pipeline(Generic[T]):
    """Pipe an async stream through ordered stages and an optional sink.

    A step is either an object with ``process(stream)`` or a plain async
    generator function ``fn(stream)``, so ad-hoc enrichment stages need no
    wrapper class.
    """

    def __init__(self) -> None:
        self.steps: list[StreamTransform] = []
        self.sink: Optional[ProductSink] = None

    def add_step(self, step: StepLike) -> "Pipeline[T]":
        """Append a stage and return this pipeline for fluent configuration."""
        if isinstance(step, Stage):
            self.steps.append(step.process)
        elif callable(step):
            self.steps.append(step)
        else:
            raise TypeError(f"Pipeline step must define process() or be callable: {step!r}")
        return self

    def set_sink(self, sink: ProductSink) -> "Pipeline[T]":
        """Set the object that receives each final model as a dictionary."""
        self.sink = sink
        return self

    async def run(self, stream: AsyncIterator[T]) -> PipelineStats:
        """Consume ``stream`` through every stage and persist final items.

        Returns:
            Counts of items read from ``stream`` and items given to the sink.
        """
        stats = PipelineStats()

        async def counted(source: AsyncIterator[T]) -> AsyncIterator[T]:
            async for item in source:
                stats.extracted += 1
                yield item

        current: AsyncIterator[Any] = counted(stream)
        for step in self.steps:
            current = step(current)
        async for item in current:
            if self.sink is not None:
                self.sink.load_product(item.model_dump())
            stats.loaded += 1
        return stats
