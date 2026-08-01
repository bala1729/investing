"""Tests for configuration module."""

import os
from unittest.mock import patch

from src.config import Settings, TradingMode, get_settings


class TestTradingMode:
    """Tests for TradingMode enum."""

    def test_paper_mode_value(self) -> None:
        assert TradingMode.PAPER.value == "paper"

    def test_live_mode_value(self) -> None:
        assert TradingMode.LIVE.value == "live"


class TestSettings:
    """Tests for Settings class."""

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.kraken_api_key == ""
        assert settings.kraken_api_secret == ""
        assert settings.trading_mode == TradingMode.PAPER
        assert settings.webhook_host == "0.0.0.0"
        assert settings.webhook_port == 8000
        assert settings.risk_per_trade_pct == 1.0
        assert settings.max_position_size_pct == 5.0
        assert settings.max_drawdown_pct == 10.0
        assert settings.default_stop_loss_pct == 2.0
        assert settings.max_open_positions == 5
        assert settings.log_level == "INFO"

    def test_is_paper_trading_true(self) -> None:
        """Test is_paper_trading returns True for paper mode."""
        with patch.dict(os.environ, {"TRADING_MODE": "paper"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.is_paper_trading is True

    def test_is_paper_trading_false(self) -> None:
        """Test is_paper_trading returns False for live mode."""
        with patch.dict(os.environ, {"TRADING_MODE": "live"}, clear=True):
            settings = Settings(_env_file=None)

        assert settings.is_paper_trading is False

    def test_loads_from_environment(self) -> None:
        """Test that settings load from environment variables."""
        env_vars = {
            "KRAKEN_API_KEY": "test_key",
            "KRAKEN_API_SECRET": "test_secret",
            "TRADING_MODE": "live",
            "WEBHOOK_PORT": "9000",
            "RISK_PER_TRADE_PCT": "2.0",
            "MAX_POSITION_SIZE_PCT": "10.0",
            "MAX_OPEN_POSITIONS": "3",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings(_env_file=None)

        assert settings.kraken_api_key == "test_key"
        assert settings.kraken_api_secret == "test_secret"
        assert settings.trading_mode == TradingMode.LIVE
        assert settings.webhook_port == 9000
        assert settings.risk_per_trade_pct == 2.0
        assert settings.max_position_size_pct == 10.0
        assert settings.max_open_positions == 3


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Test that get_settings returns a Settings instance."""
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_caches_settings(self) -> None:
        """Test that settings are cached."""
        get_settings.cache_clear()
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2
