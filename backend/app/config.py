from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/binance_app"

    jwt_secret_key: str = "change-me-in-.env"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # API secret'ları DB'de şifrelemek için kullanılan Fernet master key.
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
    encryption_master_key: str = "change-me-generate-a-fernet-key"

    cors_origins: list[str] = ["http://localhost:5173"]

    binance_base_url: str = "https://api.binance.com"
    binance_futures_base_url: str = "https://fapi.binance.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
