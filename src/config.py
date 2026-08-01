"""Configuration management using pydantic-settings."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(StrEnum):
    """Trading mode enumeration."""

    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Kraken API
    kraken_api_key: str = Field(default="", description="Kraken API key")
    kraken_api_secret: str = Field(default="", description="Kraken API secret")

    # Trading Mode
    trading_mode: TradingMode = Field(
        default=TradingMode.PAPER, description="Trading mode: paper or live"
    )

    # Webhook Configuration
    webhook_secret: str = Field(default="changeme", description="Secret for webhook validation")
    webhook_host: str = Field(default="0.0.0.0", description="Webhook server host")
    webhook_port: int = Field(default=8000, description="Webhook server port")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./trading_bot.db", description="Database connection URL"
    )

    # Risk Management
    risk_per_trade_pct: float = Field(
        default=1.0,
        description="Percent of account equity to risk per trade (loss if the stop-loss is "
        "hit). Drives position sizing; max_position_size_pct is a secondary cap on capital "
        "deployed, not the primary sizing driver.",
    )
    max_position_size_pct: float = Field(
        default=5.0, description="Secondary cap: maximum position size as percentage of balance"
    )
    max_drawdown_pct: float = Field(
        default=10.0, description="Maximum allowed drawdown percentage"
    )
    default_stop_loss_pct: float = Field(
        default=2.0, description="Default stop loss percentage"
    )
    max_open_positions: int = Field(
        default=5, description="Maximum number of concurrent open positions"
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str = Field(default="logs/trading_bot.log", description="Log file path")

    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self.trading_mode == TradingMode.PAPER


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
