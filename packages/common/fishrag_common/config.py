from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from os import environ
from pathlib import Path


def _get(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key)
    if value is None or value == "":
        return default
    return value


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _strip_quotes(value.strip())
    return values


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    log_level: str
    api_prefix: str
    cors_origins: tuple[str, ...]
    jwt_secret_key: str
    jwt_issuer: str
    access_token_expire_minutes: int
    storage_dir: Path
    upload_dir: Path
    max_upload_bytes: int
    database_url: str
    redis_url: str
    opensearch_url: str
    llm_provider: str
    llm_base_url: str
    llm_api_key: str
    chat_model: str
    llm_thinking: str
    embedding_provider: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    reranker_provider: str
    reranker_base_url: str
    reranker_api_key: str
    reranker_model: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = environ if env is None else env
        storage_dir = Path(_get(source, "FISHRAG_STORAGE_DIR", "storage"))
        llm_base_url = _get(source, "FISHRAG_LLM_BASE_URL", "https://api.deepseek.com")
        llm_api_key = _get(source, "FISHRAG_LLM_API_KEY", "")
        return cls(
            app_name=_get(source, "FISHRAG_APP_NAME", "FishRag"),
            environment=_get(source, "FISHRAG_ENV", "local"),
            log_level=_get(source, "FISHRAG_LOG_LEVEL", "INFO"),
            api_prefix=_get(source, "FISHRAG_API_PREFIX", "/api/v1"),
            cors_origins=_csv(
                _get(
                    source,
                    "FISHRAG_CORS_ORIGINS",
                    "http://localhost:5173,http://127.0.0.1:5173",
                )
            ),
            jwt_secret_key=_get(source, "FISHRAG_JWT_SECRET_KEY", "change-me-in-local-env"),
            jwt_issuer=_get(source, "FISHRAG_JWT_ISSUER", "fishrag"),
            access_token_expire_minutes=int(
                _get(source, "FISHRAG_ACCESS_TOKEN_EXPIRE_MINUTES", "120")
            ),
            storage_dir=storage_dir,
            upload_dir=Path(_get(source, "FISHRAG_UPLOAD_DIR", str(storage_dir / "uploads"))),
            max_upload_bytes=int(_get(source, "FISHRAG_MAX_UPLOAD_BYTES", "52428800")),
            database_url=_get(
                source,
                "FISHRAG_DATABASE_URL",
                "postgresql+asyncpg://fishrag:fishrag@localhost:5432/fishrag",
            ),
            redis_url=_get(source, "FISHRAG_REDIS_URL", "redis://localhost:6379/0"),
            opensearch_url=_get(source, "FISHRAG_OPENSEARCH_URL", "http://localhost:9200"),
            llm_provider=_get(source, "FISHRAG_LLM_PROVIDER", "deepseek"),
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            chat_model=_get(source, "FISHRAG_CHAT_MODEL", "deepseek-v4-flash"),
            llm_thinking=_get(source, "FISHRAG_LLM_THINKING", "disabled"),
            embedding_provider=_get(source, "FISHRAG_EMBEDDING_PROVIDER", "siliconflow"),
            embedding_base_url=_get(
                source,
                "FISHRAG_EMBEDDING_BASE_URL",
                "https://api.siliconflow.cn/v1",
            ),
            embedding_api_key=_get(source, "FISHRAG_EMBEDDING_API_KEY", ""),
            embedding_model=_get(source, "FISHRAG_EMBEDDING_MODEL", "BAAI/bge-m3"),
            reranker_provider=_get(source, "FISHRAG_RERANKER_PROVIDER", "siliconflow"),
            reranker_base_url=_get(
                source,
                "FISHRAG_RERANKER_BASE_URL",
                "https://api.siliconflow.cn/v1",
            ),
            reranker_api_key=_get(source, "FISHRAG_RERANKER_API_KEY", ""),
            reranker_model=_get(source, "FISHRAG_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_file = Path(_get(environ, "FISHRAG_ENV_FILE", ".env"))
    file_env = load_env_file(env_file)
    merged_env = {**file_env, **environ}
    return Settings.from_env(merged_env)
