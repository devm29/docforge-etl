from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from docforge.config import BACKEND_ROOT, Settings
from docforge.corpus.generator import generate_corpus
from docforge.db.models import Base
from docforge.domain.documents import DocumentModel
from docforge.parsing.base import default_registry, detect_format

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://docforge@localhost:5503/docforge_test"
)

ParseFn = Callable[[str], DocumentModel]


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("corpus")
    generate_corpus(root)
    return root


@pytest.fixture(scope="session")
def parse(corpus_dir: Path) -> ParseFn:
    registry = default_registry()

    def _parse(relative: str) -> DocumentModel:
        data = (corpus_dir / relative).read_bytes()
        return registry.for_format(detect_format(relative, data)).parse(data)

    return _parse


async def _ensure_database(url: str) -> bool:
    parsed = make_url(url)
    try:
        admin = await asyncpg.connect(
            host=parsed.host,
            port=parsed.port,
            user=parsed.username,
            password=parsed.password,
            database="postgres",
        )
    except (OSError, asyncpg.PostgresError):
        return False
    try:
        exists = await admin.fetchval("select 1 from pg_database where datname = $1", parsed.database)
        if not exists:
            await admin.execute(f'create database "{parsed.database}"')
    finally:
        await admin.close()
    return True


@pytest.fixture(scope="session")
async def database_url() -> AsyncIterator[str]:
    if not await _ensure_database(TEST_DATABASE_URL):
        message = "PostgreSQL with pgvector is not reachable; set TEST_DATABASE_URL"
        if os.environ.get("CI", "").lower() in {"1", "true"}:
            pytest.fail(message)
        pytest.skip(message)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    await asyncio.to_thread(command.upgrade, config, "head")
    yield TEST_DATABASE_URL


async def truncate_all(url: str) -> None:
    engine = create_async_engine(url)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    await engine.dispose()


@pytest.fixture
async def settings(tmp_path: Path, corpus_dir: Path, database_url: str) -> Settings:
    await truncate_all(database_url)
    inbox = tmp_path / "inbox"
    shutil.copytree(corpus_dir, inbox)
    return Settings(
        environment="test",
        database_url=database_url,
        data_dir=tmp_path / "data",
        corpus_dir=corpus_dir,
        fs_source_root=inbox,
        llm_provider="offline",
        embedding_provider="hashing",
        stage_backoff_base_seconds=0.0,
        stage_backoff_max_seconds=0.0,
        anthropic_api_key=None,
    )
