# -*- coding: utf-8 -*-
"""One-time storage migration: copy every row from a SQLite database
into a target SQL database (PostgreSQL / MySQL) of the same schema.

The target schema is created from the source's reflected definitions
AFTER normalizing SQLite's legacy upper-case generic types (DATETIME,
DATE, TIME, BLOB, CLOB) to their portable modern equivalents — the
legacy types compile verbatim (``DATETIME``) on PostgreSQL, which has
no such type. Values stored as ISO strings in SQLite are parsed into
real datetime/date objects for the insert. Refuses to run against a
target that already holds rows, so a re-run cannot duplicate data.

Usage:
    python scripts/migrate_sqlite_to_sql.py \
        --target "postgresql+asyncpg://agentscope:PASSWORD@localhost:5432/agentscope"
"""
import argparse
import asyncio
from datetime import date as _date
from datetime import datetime as _datetime

import sqlalchemy.types as satypes
from sqlalchemy import Date, DateTime, LargeBinary, MetaData, Text, Time
from sqlalchemy.ext.asyncio import create_async_engine

# Internal bookkeeping table — not business data.
_SKIPPED_TABLES = {"alembic_version"}


def _normalize_types(meta: MetaData) -> None:
    """Replace SQLite's legacy upper-case generic types with the portable
    modern ones, in place.

    Args:
        meta (`MetaData`): The reflected source metadata.
    """
    for table in meta.tables.values():
        for column in table.columns:
            if isinstance(column.type, satypes.DATETIME):
                column.type = DateTime()
            elif isinstance(column.type, satypes.DATE):
                column.type = Date()
            elif isinstance(column.type, satypes.TIME):
                column.type = Time()
            elif isinstance(column.type, satypes.BLOB):
                column.type = LargeBinary()
            elif isinstance(column.type, satypes.CLOB):
                column.type = Text()


def _convert_row(table, row: dict) -> dict:
    """Parse ISO strings into real datetime/date objects where the
    target column expects them (asyncpg rejects strings for
    timestamp/date parameters).

    Args:
        table: The normalized target table.
        row (`dict`): One row fetched from SQLite.

    Returns:
        `dict`: The same row with datetime columns converted.
    """
    for column in table.columns:
        value = row.get(column.name)
        if not isinstance(value, str):
            continue
        if isinstance(column.type, DateTime):
            try:
                row[column.name] = _datetime.fromisoformat(value)
            except ValueError:
                pass
        elif isinstance(column.type, Date):
            try:
                row[column.name] = _date.fromisoformat(value)
            except ValueError:
                pass
    return row


async def migrate(source_url: str, target_url: str) -> None:
    """Copy all rows from ``source_url`` into ``target_url``."""
    source_engine = create_async_engine(source_url)
    target_engine = create_async_engine(target_url)
    try:
        meta = MetaData()
        async with source_engine.begin() as conn:
            await conn.run_sync(meta.reflect)
        tables = [
            t for name, t in meta.tables.items()
            if name not in _SKIPPED_TABLES
        ]
        if not tables:
            raise SystemExit("Source database has no tables to migrate.")

        _normalize_types(meta)

        # Build the target schema from the normalized definitions.
        async with target_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: meta.create_all(
                    sync_conn,
                    tables=tables,
                ),
            )

        # Safety: refuse a target that already holds data.
        for table in tables:
            async with target_engine.connect() as conn:
                count = (await conn.execute(table.count())).scalar_one()
            if count:
                raise SystemExit(
                    f"Target table '{table.name}' already has {count} "
                    "rows — refusing to migrate into a non-empty "
                    "database.",
                )

        total = 0
        async with target_engine.begin() as tconn:
            for table in meta.sorted_tables:
                if table.name in _SKIPPED_TABLES:
                    continue
                async with source_engine.connect() as sconn:
                    rows = (await sconn.execute(
                        table.select(),
                    )).mappings().all()
                if rows:
                    await tconn.execute(
                        table.insert(),
                        [_convert_row(table, dict(row)) for row in rows],
                    )
                print(f"  {table.name}: {len(rows)} 行")
                total += len(rows)
        print(f"迁移完成,共 {total} 行。")
    finally:
        await source_engine.dispose()
        await target_engine.dispose()


def main() -> None:
    """Parse arguments and run the migration."""
    parser = argparse.ArgumentParser(
        description="Migrate agentscope storage from SQLite to another "
        "SQL database (PostgreSQL / MySQL).",
    )
    parser.add_argument(
        "--source",
        default="sqlite+aiosqlite:///examples/agent_service/workspaces/agentscope.db",
        help="Source SQLAlchemy URL (default: the local SQLite file).",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Target SQLAlchemy URL, e.g. "
        "postgresql+asyncpg://agentscope:PASSWORD@localhost:5432/agentscope",
    )
    args = parser.parse_args()
    asyncio.run(migrate(args.source, args.target))


if __name__ == "__main__":
    main()
