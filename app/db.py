from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.config import settings


class Base(DeclarativeBase):
    pass


class Datastore:
    def __init__(self, database_url: str | None = None):
        self.url = database_url or settings.DATABASE_URL
        if ":memory:" in self.url:
            self.engine: AsyncEngine = create_async_engine(
                self.url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            self.engine: AsyncEngine = create_async_engine(self.url)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def ensure_tables(self) -> None:
        # Import all ORMs so they register onto Base.metadata
        import correlation.db  # noqa: F401
        import investigation.db  # noqa: F401

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()


_datastore: Datastore | None = None


def get_datastore() -> Datastore:
    global _datastore
    if _datastore is None:
        _datastore = Datastore()
    return _datastore


async def close_datastore() -> None:
    global _datastore
    if _datastore is not None:
        await _datastore.close()
        _datastore = None
