from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent

LlmProviderName = Literal["auto", "anthropic", "offline"]
EmbeddingProviderName = Literal["auto", "fastembed", "hashing"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "postgresql+asyncpg://docforge@localhost:5503/docforge"
    redis_url: str = "redis://:docforge-dev@localhost:6403/0"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3103"])
    # Bearer token -> principal name. Without tokens, writes are only accepted from loopback.
    api_tokens: dict[str, str] = Field(default_factory=dict)

    data_dir: Path = PROJECT_ROOT / "data"
    corpus_dir: Path = PROJECT_ROOT / "sample-corpus"

    fs_source_root: Path = PROJECT_ROOT / "data" / "inbox"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "docforge-inbox"
    s3_prefix: str = ""
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None

    llm_provider: LlmProviderName = "auto"
    anthropic_api_key: SecretStr | None = None
    extraction_model: str = "claude-opus-5-5"
    extraction_effort: Effort = "medium"
    extraction_max_repairs: int = Field(default=2, ge=0, le=5)
    extraction_refusal_fallback: bool = True
    review_confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    schema_modules: list[str] = Field(
        default_factory=list, description="Importable modules exposing SCHEMAS: list[SchemaSpec]"
    )

    embedding_provider: EmbeddingProviderName = "auto"
    fastembed_model: str = "BAAI/bge-small-en-v1.5"

    chunk_max_tokens: int = Field(default=320, ge=64, le=2048)
    chunk_overlap_blocks: int = Field(default=1, ge=0, le=4)

    stage_max_attempts: int = Field(default=3, ge=1, le=10)
    stage_backoff_base_seconds: float = Field(default=0.5, ge=0.0)
    stage_backoff_max_seconds: float = Field(default=20.0, ge=0.0)
    worker_max_jobs: int = Field(default=4, ge=1)
    worker_job_tries: int = Field(default=3, ge=1)
    # Longer than the worker's 10-minute job timeout, so a live job is never mistaken for a stalled one.
    run_stale_after_seconds: int = Field(default=900, ge=660)

    scheduled_scan_enabled: bool = False
    scheduled_scan_minute_interval: int = Field(default=15, ge=1, le=60)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
