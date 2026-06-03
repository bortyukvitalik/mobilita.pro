"""Подключение к БД: async-движок, фабрика сессий, инициализация схемы."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings
from .models import Base

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Создаёт таблицы, если их ещё нет (на старте приложения)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session
