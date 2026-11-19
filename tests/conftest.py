
import os
from dotenv import load_dotenv

load_dotenv(override=True)
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
)
from sqlalchemy.pool import NullPool

from app.database import Base, get_db
from app.main import app


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is missing. Configure a dedicated test database."
    )

if not TEST_DATABASE_URL.startswith("postgresql+psycopg://"):
    raise RuntimeError(
        "TEST_DATABASE_URL must use postgresql+psycopg://"
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    test_engine = create_async_engine(
        TEST_DATABASE_URL,
        pool_pre_ping=True,
        poolclass=NullPool,
    )

    yield test_engine

    await test_engine.dispose()


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def setup_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def db_session(engine, setup_db):
    async with engine.connect() as connection:
        transaction = await connection.begin()

        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

        if transaction.is_active:
            await transaction.rollback()


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def override_get_db(db_session):
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override

    yield

    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture(scope="function", loop_scope="session")
async def client(override_get_db):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as async_client:
        yield async_client
