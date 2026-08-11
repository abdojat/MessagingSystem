import asyncio
import os
import re

from sqlalchemy import text

from app.db.session import engine


ROLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


async def grant_runtime_role() -> None:
    """Grant maintainable application CRUD privileges after Alembic runs."""

    role = os.environ.get("POSTGRES_APP_USER", "").strip()
    if not ROLE_NAME_RE.fullmatch(role):
        raise RuntimeError("POSTGRES_APP_USER must be a valid PostgreSQL role identifier")

    quoted_role = f'"{role}"'
    async with engine.begin() as conn:
        database_name = (await conn.execute(text("SELECT current_database()"))).scalar_one()
        if not ROLE_NAME_RE.fullmatch(database_name):
            raise RuntimeError("database name must be a simple PostgreSQL identifier")
        quoted_database = f'"{database_name}"'

        await conn.execute(text(f"ALTER ROLE {quoted_role} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"))
        await conn.execute(text(f"GRANT CONNECT ON DATABASE {quoted_database} TO {quoted_role}"))
        await conn.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_role}"))
        await conn.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted_role}")
        )
        await conn.execute(
            text(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {quoted_role}")
        )
        await conn.execute(
            text(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted_role}"
            )
        )
        await conn.execute(
            text(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {quoted_role}"
            )
        )


def main() -> None:
    asyncio.run(grant_runtime_role())


if __name__ == "__main__":
    main()
