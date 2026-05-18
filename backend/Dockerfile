FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN useradd --create-home --uid 10001 docforge

COPY backend/pyproject.toml ./
COPY backend/src ./src
RUN pip install ".[fastembed]"

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY sample-corpus /app/sample-corpus

ENV DATA_DIR=/data \
    CORPUS_DIR=/app/sample-corpus \
    FS_SOURCE_ROOT=/data/inbox

RUN mkdir -p /data && chown docforge:docforge /data
USER docforge

EXPOSE 8103
CMD ["sh", "-c", "alembic upgrade head && uvicorn docforge.api.app:create_app --factory --host 0.0.0.0 --port 8103"]
