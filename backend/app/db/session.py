from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Retrieves db; the application startup and service layers use it for database access.
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # Keep `SessionLocal()` active while this scoped operation is performed.
    async with SessionLocal() as session:
        yield session
