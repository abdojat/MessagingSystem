import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import encryption
from app.core.config import get_settings
from app.db.models import Base

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/channels")
os.environ.setdefault("MESSAGE_ENCRYPTION_ENABLED", "true")
os.environ.setdefault("MESSAGE_ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
os.environ.setdefault("JWT_SECRET", "test-secret")


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    encryption._build_fernet.cache_clear()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/channels")
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("ALTER TYPE outbox_status ADD VALUE IF NOT EXISTS 'publishing'"))
            await conn.execute(text("ALTER TYPE outbox_status ADD VALUE IF NOT EXISTS 'published'"))
            await conn.execute(text("ALTER TYPE outbox_status ADD VALUE IF NOT EXISTS 'retry_scheduled'"))
            await conn.execute(text("ALTER TYPE outbox_status ADD VALUE IF NOT EXISTS 'dead_lettered'"))
            await conn.execute(text("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 5"))
            await conn.execute(text("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now()"))
            await conn.execute(text("ALTER TABLE outbox ADD COLUMN IF NOT EXISTS dead_lettered_at timestamptz"))
            await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS previous_hash varchar(64)"))
            await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS event_hash varchar(64)"))
            await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS hash_algorithm varchar(32)"))
            await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS integrity_version integer"))
            await conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS integrity_scope varchar(128)"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallpaper_url text"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superadmin boolean NOT NULL DEFAULT false"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at timestamptz"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_by_user_id uuid"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL test database is not reachable for DATABASE_URL={database_url!r}: {exc}")
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        # Isolate test cases while reusing a migrated schema.
        await session.execute(text("TRUNCATE TABLE outbox, events, user_channel_state, pinned_messages, message_reactions, messages, channel_invites, channel_memberships, channel_counters, channels, user_sessions, users RESTART IDENTITY CASCADE"))
        await session.commit()
        yield session
    await engine.dispose()
