from pathlib import Path
from typing import Any, Dict, Optional

from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from pydantic import PostgresDsn, RedisDsn, field_validator
from pydantic_core.core_schema import FieldValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import ConnectionPool, Redis


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file="source/backend/.env", extra="ignore")


class Settings(BaseSettings):
    API_V1: str = "/v1"
    API_V2: str = "/v2"
    ROOT_PATH: str = "/api"
    ALLOWED_HOSTS: list[str] = ["*"]

    debug: bool = True
    title: str = "FastAPI backend application"
    version: str = "0.3.0b"
    openapi_url: str = f"{API_V1}/openapi.json"
    docs_url: str = f"{API_V1}/docs"
    redoc_url: str = f"{API_V1}/redoc"
    openapi_prefix: str = ""

    @property
    def fastapi_kwargs(self) -> Dict[str, Any]:
        return {
            "debug": self.debug,
            "title": self.title,
            "version": self.version,
            "openapi_url": self.openapi_url,
            "docs_url": self.docs_url,
            "redoc_url": self.redoc_url,
            # "root_path": self.ROOT_PATH,
            "openapi_prefix": self.openapi_prefix,
        }

    class Database(ServiceSettings):
        POSTGRES_USER: str
        POSTGRES_PASSWORD: str
        POSTGRES_HOST: str
        POSTGRES_PORT: int
        POSTGRES_DB: str

        SQLALCHEMY_DATABASE_URI: Optional[str] = None

        @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
        def assemble_db_connection(
            cls,  # noqa: N805
            v: Optional[str],
            info: FieldValidationInfo,
        ) -> Any:
            if isinstance(v, str):
                return v
            return str(
                PostgresDsn.build(
                    scheme="postgresql+asyncpg",
                    username=info.data.get("POSTGRES_USER"),
                    password=info.data.get("POSTGRES_PASSWORD"),
                    host=info.data.get("POSTGRES_HOST"),
                    port=info.data.get("POSTGRES_PORT"),
                    path=f"{info.data.get('POSTGRES_DB') or ''}",
                )
            )

    class Authentication(ServiceSettings):
        TOKEN_TYPE: str = "bearer"
        ACCESS_TOKEN_EXPIRE_MINUTES: int = 5
        REFRESH_TOKEN_EXPIRE_DAYS: int = 30
        JWT_PRIVATE_PATH: Path
        JWT_PUBLIC_PATH: Path
        ALGORITHM: str = "RS256"

    class RedisCache(ServiceSettings):
        REDIS_USER: Optional[str] = "default"
        REDIS_PASSWORD: str
        REDIS_HOST: str
        REDIS_PORT: int

        REDIS_URI: Optional[str] = None

        @field_validator("REDIS_URI", mode="before")
        def assemble_db_connection(
            cls,  # noqa: N805
            v: Optional[str],
            info: FieldValidationInfo,
        ) -> Any:
            if isinstance(v, str):
                return v
            return str(
                RedisDsn.build(
                    scheme="redis",
                    host=info.data.get("REDIS_HOST"),
                    port=info.data.get("REDIS_PORT"),
                )
            )

        async def setup_cache(self) -> None:
            pool = ConnectionPool.from_url(url=self.REDIS_URI)
            redis = Redis(connection_pool=pool)
            FastAPICache.init(RedisBackend(redis=redis), prefix="redis_cache")


config: Settings = Settings()
