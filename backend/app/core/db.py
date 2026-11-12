from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def _sync_factory() -> sessionmaker[Session]:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


@lru_cache
def _async_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    with _sync_factory()() as session, session.begin():
        yield session


def new_async_session() -> AsyncSession:
    return _async_factory()()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _async_factory()() as session:
        yield session


def get_sync_session() -> Iterator[Session]:
    with _sync_factory()() as session:
        yield session
