from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from docforge.api.deps import Services
from docforge.api.errors import install_error_handlers
from docforge.api.routes import documents, misc, reviews, runs
from docforge.config import Settings, get_settings
from docforge.container import Container, build_container
from docforge.logs import configure_logging
from docforge.pipeline.queue import ArqJobQueue, JobQueue, deserialize_job, serialize_job


def create_app(
    settings: Settings | None = None, *, container: Container | None = None, queue: JobQueue | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    if settings.environment == "production" and not settings.api_tokens:
        raise RuntimeError("API_TOKENS must be set in production")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        active = container or build_container(settings)
        redis = None
        active_queue = queue
        if active_queue is None:
            redis = await create_pool(
                RedisSettings.from_dsn(settings.redis_url),
                job_serializer=serialize_job,
                job_deserializer=deserialize_job,
            )
            active_queue = ArqJobQueue(redis)
        app.state.services = Services.build(active, active_queue)
        try:
            yield
        finally:
            if redis is not None:
                await redis.aclose()
            if owned:
                await active.close()

    app = FastAPI(
        title="DocForge API",
        version="0.1.0",
        description="Incremental document-intelligence ETL with field-level provenance.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type"],
    )
    install_error_handlers(app)
    for router in (misc.router, runs.router, documents.router, reviews.router):
        app.include_router(router, prefix="/api")
    return app
