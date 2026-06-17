from __future__ import annotations

from pathlib import Path

from fishrag_common.config import Settings, load_env_file


def test_settings_defaults_are_loaded() -> None:
    settings = Settings.from_env({})

    assert settings.app_name == "FishRag"
    assert settings.api_prefix == "/api/v1"
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert "http://localhost:5173" in settings.cors_origins
    assert settings.llm_provider == "deepseek"
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.chat_model == "deepseek-v4-flash"
    assert settings.llm_thinking == "disabled"
    assert settings.embedding_provider == "siliconflow"
    assert settings.embedding_base_url == "https://api.siliconflow.cn/v1"
    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.reranker_provider == "siliconflow"
    assert settings.reranker_base_url == "https://api.siliconflow.cn/v1"
    assert settings.reranker_model == "BAAI/bge-reranker-v2-m3"


def test_settings_can_read_custom_values() -> None:
    settings = Settings.from_env(
        {
            "FISHRAG_APP_NAME": "CustomRag",
            "FISHRAG_CORS_ORIGINS": "http://localhost:3000, http://example.com",
            "FISHRAG_LLM_BASE_URL": "https://chat.example/v1",
            "FISHRAG_LLM_API_KEY": "chat-key",
            "FISHRAG_CHAT_MODEL": "chat-model",
            "FISHRAG_LLM_THINKING": "enabled",
            "FISHRAG_EMBEDDING_BASE_URL": "https://embedding.example/v1",
            "FISHRAG_EMBEDDING_API_KEY": "embedding-key",
            "FISHRAG_EMBEDDING_MODEL": "embedding-model",
        }
    )

    assert settings.app_name == "CustomRag"
    assert settings.cors_origins == ("http://localhost:3000", "http://example.com")
    assert settings.llm_base_url == "https://chat.example/v1"
    assert settings.llm_api_key == "chat-key"
    assert settings.chat_model == "chat-model"
    assert settings.llm_thinking == "enabled"
    assert settings.embedding_base_url == "https://embedding.example/v1"
    assert settings.embedding_api_key == "embedding-key"
    assert settings.embedding_model == "embedding-model"


def test_load_env_file_reads_simple_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "FISHRAG_APP_NAME=FromEnvFile",
                "FISHRAG_LLM_API_KEY='quoted-key'",
                "EMPTY=",
            ]
        ),
        encoding="utf-8",
    )

    values = load_env_file(env_file)

    assert values["FISHRAG_APP_NAME"] == "FromEnvFile"
    assert values["FISHRAG_LLM_API_KEY"] == "quoted-key"
    assert values["EMPTY"] == ""
