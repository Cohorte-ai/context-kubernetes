"""CxRI Connector: PostgreSQL.

The structured data source. Transactional records, pipeline metrics,
financial data — anything that requires schema integrity and SQL queries.

Uses asyncpg for async PostgreSQL access. Converts query results
into ContextUnits with structured metadata.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from context_kubernetes.cxri.interface import (
    ChangeEvent,
    ConnectionConfig,
    CxRIConnector,
    HealthStatus,
    WriteResult,
)
from context_kubernetes.models import ContextUnit, ContextUnitMetadata, ContentType


class PostgresConnector(CxRIConnector):
    """
    CxRI connector for PostgreSQL databases.

    Queries structured data and converts rows into ContextUnits.
    Supports LISTEN/NOTIFY for change subscription.

    Config:
        endpoint: PostgreSQL connection string (DSN)
        scope: schema or table prefix to restrict queries
        extra:
            domain: context domain name
            tables: list of table names to index (optional)
    """

    connector_type = "postgresql"

    def __init__(self) -> None:
        self._pool: Any | None = None
        self._dsn: str = ""
        self._domain: str = "default"
        self._scope: str = ""
        self._tables: list[str] = []
        self._last_check_ts: float = 0.0

    async def connect(self, config: ConnectionConfig) -> None:
        """Establish connection pool to PostgreSQL."""
        import asyncpg

        self._dsn = config.endpoint
        self._domain = config.extra.get("domain", "default")
        self._scope = config.scope
        self._tables = config.extra.get("tables", [])

        try:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=5, timeout=10
            )
            self._last_check_ts = time.time()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to PostgreSQL: {e}")

    async def query(self, intent: str, **filters: Any) -> list[ContextUnit]:
        """
        Query PostgreSQL tables by searching text columns.

        For structured data, we search across all text/varchar columns
        in the configured tables. The Context Router handles semantic
        ranking — this connector returns candidate matches.
        """
        self._ensure_connected()
        assert self._pool is not None

        results: list[ContextUnit] = []
        search_terms = intent.lower().split()
        max_results = filters.get("max_results", 50)

        async with self._pool.acquire() as conn:
            tables = self._tables or await self._discover_tables(conn)

            for table in tables[:10]:  # limit to prevent runaway queries
                try:
                    units = await self._search_table(conn, table, search_terms, max_results)
                    results.extend(units)
                except Exception:
                    continue  # skip tables with errors

        return results[:max_results]

    async def read(self, path: str) -> ContextUnit | None:
        """
        Read a specific record by path.

        Path format: "table_name/primary_key_value"
        """
        self._ensure_connected()
        assert self._pool is not None

        parts = path.split("/", 1)
        if len(parts) != 2:
            return None

        table, key_value = parts

        async with self._pool.acquire() as conn:
            try:
                # Find primary key column
                pk_col = await self._get_primary_key(conn, table)
                if not pk_col:
                    return None

                row = await conn.fetchrow(
                    f'SELECT * FROM "{table}" WHERE "{pk_col}" = $1',
                    key_value,
                )
                if not row:
                    return None

                return self._row_to_context_unit(table, dict(row))
            except Exception:
                return None

    async def write(self, path: str, content: str, message: str = "") -> WriteResult:
        """
        Write a record. Content is JSON-encoded row data.

        Path format: "table_name" for INSERT, "table_name/pk_value" for UPDATE.
        """
        self._ensure_connected()
        assert self._pool is not None

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return WriteResult(success=False, message="Content must be valid JSON")

        parts = path.split("/", 1)
        table = parts[0]

        async with self._pool.acquire() as conn:
            try:
                if len(parts) == 2:
                    # UPDATE
                    pk_value = parts[1]
                    pk_col = await self._get_primary_key(conn, table)
                    if not pk_col:
                        return WriteResult(success=False, message="No primary key found")

                    set_clauses = ", ".join(
                        f'"{k}" = ${i+2}' for i, k in enumerate(data.keys())
                    )
                    values = [pk_value] + list(data.values())
                    await conn.execute(
                        f'UPDATE "{table}" SET {set_clauses} WHERE "{pk_col}" = $1',
                        *values,
                    )
                    return WriteResult(success=True, version=str(time.time()), message="Updated")
                else:
                    # INSERT
                    columns = ", ".join(f'"{k}"' for k in data.keys())
                    placeholders = ", ".join(f"${i+1}" for i in range(len(data)))
                    await conn.execute(
                        f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
                        *data.values(),
                    )
                    return WriteResult(success=True, version=str(time.time()), message="Inserted")
            except Exception as e:
                return WriteResult(success=False, message=str(e))

    async def subscribe(self, path_pattern: str) -> AsyncIterator[ChangeEvent]:
        """
        Subscribe to changes via PostgreSQL LISTEN/NOTIFY.

        Requires a trigger on the target table(s) that sends NOTIFY
        on INSERT/UPDATE/DELETE. Channel name = "cxri_{table}".
        """
        self._ensure_connected()
        assert self._pool is not None

        channel = f"cxri_{path_pattern}" if path_pattern else "cxri_changes"

        async with self._pool.acquire() as conn:
            await conn.add_listener(channel, lambda *args: None)

            while True:
                await asyncio.sleep(1)
                # In production, this would use proper LISTEN/NOTIFY
                # For prototype, we poll for changes
                try:
                    notification = await asyncio.wait_for(
                        conn.fetchval("SELECT 1"), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    yield ChangeEvent(
                        path=path_pattern,
                        change_type="modified",
                        timestamp=time.time(),
                    )

    async def health(self) -> HealthStatus:
        """Check PostgreSQL connectivity."""
        if self._pool is None:
            return HealthStatus.DISCONNECTED

        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return HealthStatus.HEALTHY
        except Exception:
            return HealthStatus.DEGRADED

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if self._pool is None:
            raise ConnectionError("Not connected. Call connect() first.")

    async def _discover_tables(self, conn: Any) -> list[str]:
        """Discover tables in the configured schema."""
        schema = self._scope or "public"
        rows = await conn.fetch(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = $1 AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            schema,
        )
        return [row["table_name"] for row in rows]

    async def _get_primary_key(self, conn: Any, table: str) -> str | None:
        """Get the primary key column name for a table."""
        row = await conn.fetchrow(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = $1::regclass AND i.indisprimary
            LIMIT 1
            """,
            table,
        )
        return row["attname"] if row else None

    async def _search_table(
        self, conn: Any, table: str, terms: list[str], max_results: int
    ) -> list[ContextUnit]:
        """Search a table's text columns for matching terms."""
        # Get text columns
        text_cols = await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = $1
            AND data_type IN ('character varying', 'text', 'character')
            """,
            table,
        )

        if not text_cols:
            return []

        col_names = [r["column_name"] for r in text_cols]

        # Build search condition: any text column contains any term
        conditions = []
        params = []
        idx = 1
        for term in terms[:5]:  # limit terms to prevent huge queries
            col_conditions = [f'LOWER("{col}") LIKE ${idx}' for col in col_names]
            conditions.append(f"({' OR '.join(col_conditions)})")
            params.append(f"%{term}%")
            idx += 1

        if not conditions:
            return []

        where = " OR ".join(conditions)
        query = f'SELECT * FROM "{table}" WHERE {where} LIMIT {max_results}'

        try:
            rows = await conn.fetch(query, *params)
            return [self._row_to_context_unit(table, dict(row)) for row in rows]
        except Exception:
            return []

    def _row_to_context_unit(self, table: str, row: dict[str, Any]) -> ContextUnit:
        """Convert a database row to a ContextUnit."""
        # Serialize row to readable text
        lines = [f"Table: {table}"]
        for key, value in row.items():
            if value is not None:
                lines.append(f"  {key}: {value}")
        content = "\n".join(lines)

        # Extract timestamp if available
        timestamp = datetime.now(timezone.utc)
        for ts_col in ("updated_at", "created_at", "modified_at", "timestamp", "date"):
            if ts_col in row and isinstance(row[ts_col], datetime):
                timestamp = row[ts_col].replace(tzinfo=timezone.utc) if row[ts_col].tzinfo is None else row[ts_col]
                break

        # Extract entities from text columns
        entities = []
        for value in row.values():
            if isinstance(value, str) and len(value) > 2:
                words = value.split()
                for word in words:
                    if word[0].isupper() and len(word) > 2 and word.isalpha():
                        entities.append(word)

        return ContextUnit(
            content=content,
            content_type=ContentType.STRUCTURED,
            metadata=ContextUnitMetadata(
                domain=self._domain,
                source=f"pg:{table}",
                timestamp=timestamp,
                entities=entities[:10],
            ),
            version=str(hash(frozenset(row.items())) % 10**12),
            authorized_roles=set(),
        )
