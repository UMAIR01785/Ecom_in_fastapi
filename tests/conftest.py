
import os

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
)
from sqlalchemy.pool import NullPool
from app.config import settings
from app.database import Base, get_db
from app.main import app

# Require a dedicated PostgreSQL test database.
TEST_DATABASE_URL = settings.database_url

if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is missing. Configure a separate PostgreSQL test database."
    )

if not TEST_DATABASE_URL.startswith("postgresql+psycopg://"):
    raise RuntimeError(
        "TEST_DATABASE_URL must use postgresql+psycopg://"
    )

engine = create_async_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
    poolclass=NullPool,
)


@pytest_asyncio.fixture
async def setup_db():
    """Create and remove test tables for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session(setup_db):
    """Provide an isolated transactional database session."""
    async with engine.connect() as connection:
        transaction = await connection.begin()

        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

        await transaction.rollback()


@pytest_asyncio.fixture
async def override_get_db(db_session):
    """Override FastAPI database dependency."""
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override

    yield

    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def client(override_get_db):
    """Provide an async HTTP client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest_asyncio.fixture
async def dispose_test_engine():
    yield
    await engine.dispose()
