from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_model_alt: str = Field(
        default="llama3.2:3b",
        validation_alias=AliasChoices("OLLAMA_MODEL_ALT", "OLLAMA_SECONDARY_MODEL"),
    )
    log_level: str = "INFO"
    admin_api_key: str | None = None
    gateway_admin_emails: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    openai_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_BASE_URL", "OPENROUTER_BASE_URL"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "OPENROUTER_API_KEY"),
    )
    openrouter_site_url: str | None = None
    openrouter_app_name: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
