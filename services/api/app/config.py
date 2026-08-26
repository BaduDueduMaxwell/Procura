from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def find_policy_path(start: Path | None = None) -> Path:
    start = start or Path(__file__).resolve()
    for parent in start.parents:
        candidate = parent / "knowledge" / "PROCUREMENT_POLICY.md"
        if candidate.exists():
            return candidate
    return Path("/knowledge/PROCUREMENT_POLICY.md")


class Settings(BaseSettings):
    llm_provider: str = "local"
    llm_model: str = "gpt-4.1-mini"
    llm_api_key: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    sentry_dsn: str | None = None
    database_url: str = "sqlite:///./procura.db"
    app_env: str = "development"
    web_origin: str = "http://localhost:3001"
    session_cookie_name: str = "procura_session"
    session_days: int = 7
    bootstrap_buyer_email: str | None = None
    bootstrap_buyer_password: str | None = None
    bootstrap_reviewer_email: str | None = None
    bootstrap_reviewer_password: str | None = None
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_supplier_email: str | None = None
    bootstrap_supplier_password: str | None = None
    policy_path: Path = find_policy_path()
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
