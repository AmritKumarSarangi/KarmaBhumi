"""
config.py – Centralised application configuration via pydantic-settings.
All values can be overridden by environment variables (or a .env file).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────
    DB_URL: str = Field(
        default="postgresql+asyncpg://exchange:exchange@postgres:5432/exchange",
        description="Async SQLAlchemy connection string",
    )

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection URL used by aioredis",
    )

    # ── Kafka ─────────────────────────────────────────────────
    KAFKA_BROKERS: str = Field(
        default="kafka:9092",
        description="Comma-separated Kafka bootstrap servers",
    )
    KAFKA_GROUP_ID: str = Field(default="exchange-backend-group")

    # ── Matching Engine gRPC ──────────────────────────────────
    MATCHING_ENGINE_HOST: str = Field(
        default="matching-engine",
        description="Hostname of the C++ matching engine",
    )
    MATCHING_ENGINE_PORT: int = Field(default=50051)

    # ── JWT Auth ──────────────────────────────────────────────
    JWT_SECRET: str = Field(
        default="CHANGE_ME_IN_PRODUCTION_USE_LONG_RANDOM_STRING",
        description="HMAC-SHA256 signing key for JWTs",
    )
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_EXPIRE_MINUTES: int = Field(default=1440)  # 24 hours

    # ── Application ───────────────────────────────────────────
    APP_ENV: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    CORS_ORIGINS: list[str] = Field(default=["*"])

    # ── Order book Redis TTL ──────────────────────────────────
    ORDER_BOOK_CACHE_TTL_SECONDS: int = Field(default=2)

    @property
    def grpc_target(self) -> str:
        return f"{self.MATCHING_ENGINE_HOST}:{self.MATCHING_ENGINE_PORT}"

    @property
    def kafka_brokers_list(self) -> list[str]:
        return [b.strip() for b in self.KAFKA_BROKERS.split(",")]


settings = Settings()
