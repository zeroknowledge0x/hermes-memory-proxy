"""Config loader — fail-fast validation of env + settings.

Loads from environment (and .env if present). Missing required fields
raise at startup rather than surfacing as runtime errors later.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = Field(..., alias="DATABASE_URL")

    # Upstream provider
    upstream_base_url: str = Field(..., alias="UPSTREAM_BASE_URL")
    upstream_api_key: str | None = Field(None, alias="UPSTREAM_API_KEY")
    nous_auth_file: str | None = Field(None, alias="NOUS_AUTH_FILE")
    # Which adapter to use. One of: openai | anthropic
    # (Gemini/Ollama/vLLM/LM Studio are OpenAI-compatible -> "openai")
    provider_type: str = Field("openai", alias="PROVIDER_TYPE")
    # Model used by the fact-extractor LLM call (cheap model is fine)
    extraction_model: str = Field("tencent/hy3:free", alias="EXTRACTION_MODEL")

    # Server
    bind_host: str = Field("127.0.0.1", alias="BIND_HOST")
    bind_port: int = Field(8000, alias="BIND_PORT")
    auth_token: str | None = Field(None, alias="AUTH_TOKEN")
    rate_limit_per_min: int = Field(0, alias="RATE_LIMIT_PER_MIN")

    # Embedding (multilingual — D-014)
    embedding_model: str = Field(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        alias="EMBEDDING_MODEL",
    )
    embedding_dim: int = Field(384, alias="EMBEDDING_DIM")

    # Context budget
    context_window: int = Field(8192, alias="CONTEXT_WINDOW")
    reserved_pct: float = Field(0.25, alias="RESERVED_PCT")

    # Identity
    default_user_id: str = Field(
        "00000000-0000-0000-0000-000000000001", alias="DEFAULT_USER_ID"
    )
    # D-026: single-user deployment — all traffic maps to default_user_id.
    # Set false only for true multi-tenant.
    single_user_mode: bool = Field(True, alias="SINGLE_USER_MODE")

    # Fact extraction
    extraction_enabled: bool = Field(False, alias="EXTRACTION_ENABLED")


def load_settings(**overrides) -> Settings:
    """Load & validate settings. Raises pydantic ValidationError if
    required fields missing — fail fast."""
    return Settings(**overrides)
