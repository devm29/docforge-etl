from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

SessionFactory = async_sessionmaker[AsyncSession]


def create_engine(database_url: str, *, pool_size: int = 10) -> AsyncEngine:
    return create_async_engine(database_url, pool_size=pool_size, max_overflow=10, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction(factory: SessionFactory) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        yield session
