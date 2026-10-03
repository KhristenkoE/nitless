from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORDERS_", env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str = "postgresql+psycopg://orders:orders@localhost:5432/orders"
    log_level: str = "INFO"
    log_json: bool = True

    auth_secret: SecretStr = SecretStr("dev-only-auth-secret")
    default_currency: str = "USD"
    sales_tax_bps: int = 0

    payment_gateway_url: str = "https://gateway.sandbox.example.com"
    payment_gateway_api_key: SecretStr = SecretStr("dev-only-gateway-key")
    payment_gateway_timeout_seconds: float = 10.0

    webhook_url: str | None = None
    webhook_timeout_seconds: float = 5.0
    outbox_batch_size: int = 100
    outbox_max_attempts: int = 8
    outbox_poll_interval_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
