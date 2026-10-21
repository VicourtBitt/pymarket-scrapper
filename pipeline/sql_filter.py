import duckdb
from typing import AsyncIterator, List, Generic, TypeVar
from pydantic import BaseModel
import json

T = TypeVar('T', bound=BaseModel)

class SQLFilter(Generic[T]):
    """
    Accumulates yielded items into batches, loads them into DuckDB,
    and applies a custom SQL WHERE clause to filter them dynamically.
    """

    def __init__(self, model_class: type[T], where_clause: str) -> None:
        self.model_class = model_class
        self.where_clause = where_clause
        self.conn = duckdb.connect(':memory:')

    async def process(self, stream: AsyncIterator[T], batch_size: int = 50) -> AsyncIterator[T]:
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

         # 1. Map Pydantic field types to DuckDB SQL types
        type_mapping = {
            int: "BIGINT",
            float: "DOUBLE",
            str: "VARCHAR",
            bool: "BOOLEAN"
        }

        # 2. Extract column definitions directly from the Pydantic model class
        col_defs = []
        for field_name, field_info in self.model_class.model_fields.items():
            field_type = field_info.annotation

            # Simple unwrap for Optional types (Union[type, NoneType])
            if hasattr(field_type, '__args__'):
                field_type = next((t for t in field_type.__args__ if t is not type(None)), str)

            sql_type = type_mapping.get(field_type, "VARCHAR")
            col_defs.append(f"{field_name} {sql_type}")

        col_schema = ", ".join(col_defs)

        # 3. Create a temporary table schema dynamically with correct types
        self.conn.execute("DROP TABLE IF EXISTS batch_table")
        self.conn.execute(f"CREATE TABLE batch_table ({col_schema})")

        # 4. Convert Pydantic models to standard Python dicts for insertion
        items_dict = [item.model_dump() for item in batch]
        columns = list(items_dict[0].keys())

        # 4.5 Ensure dicts/lists are stringified before hitting DuckDB
        for item in items_dict:
            for k, v in item.items():
                if isinstance(v, (dict, list)):
                    item[k] = json.dumps(v)

        # 5. Insert the batch using executemany for high performance
        insert_query = f"INSERT INTO batch_table VALUES ({', '.join(['?'] * len(columns))})"
        values_list = [list(item.values()) for item in items_dict]
        self.conn.executemany(insert_query, values_list)

        # 6. Run the user's custom SQL query
        query = f"SELECT * FROM batch_table WHERE {self.where_clause}"

        try:
            result = self.conn.execute(query)

            # 7. Map the SQL results back into our Pydantic Models safely
            res_columns = [desc[0] for desc in result.description]
            filtered_items = []

            for row in result.fetchall():
                row_dict = dict(zip(res_columns, row))

                # SAFE RE-HYDRATION: Blindly parse JSON-like strings back to dicts/lists
                for k, v in row_dict.items():
                    if isinstance(v, str) and (
                            (v.startswith('{') and v.endswith('}')) or (v.startswith('[') and v.endswith(']'))):
                        try:
                            row_dict[k] = json.loads(v)
                        except json.JSONDecodeError:
                            pass

                filtered_items.append(self.model_class(**row_dict))

            return filtered_items

        except Exception as e:
            print(f"SQL Filter Error on query [{query}]: {e}")
            return []

    def close(self) -> None:
        """Close the in-memory DuckDB connection."""
        self.conn.close()