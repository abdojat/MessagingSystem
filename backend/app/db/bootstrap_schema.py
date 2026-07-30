import asyncio

from sqlalchemy import inspect

from app.db.models import Base
from app.db.session import engine


# Ensures schema; the application startup and service layers use it for database access.
async def ensure_schema() -> None:
    # Keep `engine.begin()` active while this scoped operation is performed.
    async with engine.begin() as conn:
        table_names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        required = {"channels", "outbox"}

        # Repair databases that were stamped at head but are missing core tables.
        if not required.issubset(set(table_names)):
            await conn.run_sync(Base.metadata.create_all)


# Runs the module's command-line workflow; the application startup and service layers use it for database access.
def main() -> None:
    asyncio.run(ensure_schema())


# Run this conditional step only when `__name__ == '__main__'` is true.
if __name__ == "__main__":
    main()
