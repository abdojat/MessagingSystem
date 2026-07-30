import asyncio

from sqlalchemy import inspect

from app.db.models import Base
from app.db.session import engine


async def ensure_schema() -> None:
    async with engine.begin() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        required = {"channels", "outbox"}

        # Repair databases that were stamped at head but are missing core tables.
        if not required.issubset(set(table_names)):
            await conn.run_sync(Base.metadata.create_all)


def main() -> None:
    asyncio.run(ensure_schema())


if __name__ == "__main__":
    main()
