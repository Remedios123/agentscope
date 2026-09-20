# -*- coding: utf-8 -*-
"""One-time storage migration: copy every row from a SQLite database
into a target SQL database (PostgreSQL / MySQL) of the same schema.

The target schema is created from the source's reflected definitions,
then rows are copied table by table in dependency order. Refuses to run
against a target that already holds rows, so a re-run cannot duplicate
data.

Usage:
    python scripts/migrate_sqlite_to_sql.py \
        --target "postgresql+asyncpg://agentscope:agentscope-local@localhost:5432/agentscope"
"""
import argparse
import asyncio

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine

# Internal bookkeeping table — not business data.
_SKIPPED_TABLES = {"alembic_version"}


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

        # Build the target schema from the reflected (typed) definitions;
        # generic SQLAlchemy types translate to native target types.
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
                        [dict(row) for row in rows],
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
        "postgresql+asyncpg://agentscope:agentscope-local@localhost:5432/agentscope",
    )
    args = parser.parse_args()
    asyncio.run(migrate(args.source, args.target))


if __name__ == "__main__":
    main()
