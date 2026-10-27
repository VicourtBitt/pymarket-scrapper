import duckdb
import json
import logging
from collections.abc import AsyncIterator
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

from models.config import ProductFilter

logger = logging.getLogger("pymarket_scrapper.pipeline.sql_filter")

T = TypeVar('T', bound=BaseModel)

class SQLFilter(Generic[T]):
    """Filter Pydantic models in bounded in-memory DuckDB batches."""

    def __init__(
        self, model_class: type[T], where_clause: Optional[str] = None,
        filters: Optional[ProductFilter] = None,
    ) -> None:
        """Initialize a filter from validated filters or a trusted SQL clause."""
        self.model_class = model_class
        if filters is not None:
            self.where_clause, self.parameters = filters.as_sql()
        elif where_clause is not None:
            # Trusted internal expression API retained for batch SQL callers.
            # Never pass untrusted external input as where_clause.
            self.where_clause, self.parameters = where_clause, []
        else:
            self.where_clause, self.parameters = "TRUE", []
        self.conn = duckdb.connect(':memory:')

    async def process(self, stream: AsyncIterator[T], batch_size: int = 50) -> AsyncIterator[T]:
        """Yield items matching the configured clause, batch by batch.

        Args:
            stream: Asynchronous model stream to filter.
            batch_size: Number of models processed in one DuckDB batch.

        Yields:
            Models reconstructed from rows matching the SQL predicate.

        Raises:
            Exception: Propagates DuckDB or model-validation failures after
                logging the failed query.
        """
        batch = []
        async for item in stream:
            batch.append(item)

            if len(batch) >= batch_size:
                for filtered_item in self._filter_batch(batch):
                    yield filtered_item
                batch = []

        # Flush any remaining items in the final batch
        if batch:
            for filtered_item in self._filter_batch(batch):
                yield filtered_item

    def _filter_batch(self, batch: List[T]) -> List[T]:
        if not batch:
            return []

        query: str = "<query not constructed>"
        try:
            # 1. Map Pydantic field types to DuckDB SQL types.
            type_mapping = {
                int: "BIGINT",
                float: "DOUBLE",
                str: "VARCHAR",
                bool: "BOOLEAN",
            }
            col_defs = []
            for field_name, field_info in self.model_class.model_fields.items():
                field_type = field_info.annotation
                if hasattr(field_type, "__args__"):
                    field_type = next(
                        (t for t in field_type.__args__ if t is not type(None)), str
                    )
                col_defs.append(f"{field_name} {type_mapping.get(field_type, 'VARCHAR')}")

            col_schema = ", ".join(col_defs)
            self.conn.execute("DROP TABLE IF EXISTS batch_table")
            self.conn.execute(f"CREATE TABLE batch_table ({col_schema})")

            items_dict = [item.model_dump() for item in batch]
            columns = list(items_dict[0].keys())
            for item in items_dict:
                for key, value in item.items():
                    if isinstance(value, (dict, list)):
                        item[key] = json.dumps(value)

            insert_query = (
                f"INSERT INTO batch_table VALUES ({', '.join(['?'] * len(columns))})"
            )
            self.conn.executemany(insert_query, [list(item.values()) for item in items_dict])

            query = f"SELECT * FROM batch_table WHERE {self.where_clause}"
            result = self.conn.execute(query, self.parameters)

            res_columns = [desc[0] for desc in result.description]
            filtered_items = []
            for row in result.fetchall():
                row_dict = dict(zip(res_columns, row))
                for k, v in row_dict.items():
                    if isinstance(v, str) and (
                        (v.startswith("{") and v.endswith("}"))
                        or (v.startswith("[") and v.endswith("]"))
                    ):
                        try:
                            row_dict[k] = json.loads(v)
                        except json.JSONDecodeError:
                            pass
                filtered_items.append(self.model_class(**row_dict))
            return filtered_items
        except Exception:
            logger.exception("SQL filter failed for query [%s]", query)
            raise

    def close(self) -> None:
        """Close the in-memory DuckDB connection."""
        self.conn.close()