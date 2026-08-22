"""Configuration management using pydantic-settings."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(StrEnum):
    """Trading mode enumeration."""

    PAPER = "paper"
    LIVE = "live"


class StopEnforcement(StrEnum):
    """Which mechanism is responsible for acting on a position's stop-loss.

    Deliberately an either/or rather than a pair of independent toggles. If the
    bot polled the price *and* a stop order rested on the exchange, a move
    through the stop would trigger both: the exchange fills its stop, and the
    bot - still seeing the position in its own database - sends a second market
    sell. The second order either errors on insufficient balance or, on a margin
    account, opens an unintended short.
    """

    OFF = "off"
    POLL = "poll"
    NATIVE = "native"


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
    journal_db_path: str = Field(
        default="~/kraken-bot-state/trade_journal.db",
        description="Shared SQLite file every bot appends one row to per filled signal - "
        "entry/exit price, the strategy's reason string (RSI/SMA values for rsi_crossover), "
        "hold duration and return% on exits. Separate from database_url, which is one "
        "per-bot-per-symbol DB: this file is shared across all bots/symbols on purpose, so "
        "cross-bot patterns (e.g. correlated exits) are one query instead of an N-way join.",
    )

    # Backtesting data
    kraken_data_dir: str = Field(
        default="",
        description="Directory holding Kraken's downloadable tick-data CSVs, used by "
        "scripts/backtest.py to build candles locally instead of hitting the REST API "
        "(which caps at ~720 candles). Empty means no local data is configured.",
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
    paper_fee_pct: float = Field(
        default=0.26,
        description="Trading fee charged per fill in paper trading, as a percent of trade "
        "value. Defaults to Kraken's taker rate. Paper trading charged nothing at all until "
        "2026-08-08, which made every paper result look better than the same strategy would "
        "in live trading - and fee drag is what decided every backtest in "
        "docs/backtest-results.md. Check your account's actual fee tier; set 0 only if you "
        "deliberately want frictionless results.",
    )
    stop_enforcement: StopEnforcement = Field(
        default=StopEnforcement.OFF,
        description="Who is responsible for acting on a position's stop-loss. 'off' (the "
        "default) means nobody does: a stop is still recorded on the position for reference, "
        "but only the strategy's own exit signal ever closes a trade. 'poll' has the "
        "bot compare the ticker price against the stop on every cycle and sell at market; "
        "'native' rests a stop-loss order on the exchange, which keeps protecting the "
        "position while the bot is down. Exactly one of them enforces - running both would "
        "sell the same position twice. Paper trading never uses 'native': the paper "
        "simulator has no resting orders to fill, so it falls back to 'poll'.\n\n"
        "Defaults to 'off' because measurement said so - across 8 stop widths x 30 windows "
        "on 4h, no stop configuration beat leaving stops off, and none reduced drawdown "
        "(see docs/backtest-results.md). These strategies already exit on an indicator "
        "turn, so a price stop only converts held trades into earlier ones and pays another "
        "round trip to re-enter. Enable it deliberately, per bot, not by default.",
    )
    trailing_stop_trigger_pct: float = Field(
        default=0.0,
        description="Percent above entry that price must reach before the stop is raised. "
        "0 disables the trailing stop entirely, leaving the fixed default_stop_loss_pct "
        "stop in place.",
    )
    trailing_stop_lock_pct: float = Field(
        default=0.0,
        description="Percent above entry to move the stop to once trailing_stop_trigger_pct "
        "is reached. Must be below the trigger, or the stop would sit above the price that "
        "activates it and fill instantly. Note this is a one-step ratchet, not a "
        "continuously trailing stop: the stop moves once and then holds.",
    )
    take_profit_pct: float = Field(
        default=0.0,
        description="Flat percent above entry for the take-profit target. 0 (default) falls "
        "back to risk_reward_ratio times the stop-loss distance, RiskManager's original "
        "calculation - it does not disable a target from being computed, only which formula "
        "prices it. Measurement found a 20% target paired with take_profit_exit_pct=70 beat a "
        "no-take-profit baseline on return, win rate, and (mostly) drawdown for rsi_m2 on 4h, "
        "across BTC/ETH/SOL and every start date tested (see docs/backtest-results.md, "
        "2026-08-10). That result is scoped to rsi_m2/4h specifically - set this per bot via "
        "env var, not by changing this default, the same way stop_enforcement is opt-in.",
    )
    take_profit_exit_pct: float = Field(
        default=100.0,
        description="Percent of the position a take-profit hit closes, mirroring Backtester's "
        "take_profit_exit_pct. 100 (default) is a full exit.",
    )
    take_profit_enforcement: bool = Field(
        default=False,
        description="Whether the bot acts on a position's take-profit target at all. Off by "
        "default, same philosophy as stop_enforcement - enable it deliberately, per bot. "
        "Poll-only: no take-profit order type exists on the exchange client, so there is no "
        "'native' option the way there is for stop-loss.",
    )

    kill_switch_file: str = Field(
        default="KILL_SWITCH",
        description="Path to a file that, when present, halts all new entries. Exits are "
        "never blocked - a kill switch that trapped you in a position would be worse than "
        "none. Checked every cycle, so `touch KILL_SWITCH` stops new risk immediately "
        "without killing the process or losing the open position's management.",
    )

    # Alerting
    sms_alerts_enabled: bool = Field(
        default=False,
        description="Send SMS alerts on trade fills and on a bot found dead while holding a "
        "position. Requires the Twilio settings below plus ALERT_PHONE_NUMBER; a "
        "half-configured notifier silently does nothing rather than breaking the trading "
        "loop.",
    )
    twilio_account_sid: str = Field(
        default="", description="Twilio account SID - still required alongside the API "
        "key below, since the REST endpoint is namespaced by it even when authenticating "
        "with a key rather than the account's own auth token."
    )
    twilio_api_key_sid: str = Field(
        default="",
        description="Twilio API Key SID, used for REST auth instead of the account's own "
        "auth token. An API key can be scoped and revoked independently of the account "
        "credential, so a leak here doesn't hand over the whole Twilio account.",
    )
    twilio_api_key_secret: str = Field(
        default="", description="Secret for the API key above. Keep in .env only."
    )
    twilio_from_number: str = Field(
        default="", description="Twilio number that alerts are sent from, E.164 format"
    )
    alert_phone_number: str = Field(
        default="",
        description="Destination number for alerts, E.164 format. Keep this in .env only - "
        "it is a personal phone number and this repository is public.",
    )
    sms_timeout_seconds: float = Field(
        default=10.0,
        description="How long to wait on the SMS provider before giving up. Kept short: a "
        "slow provider must not stall a trading cycle.",
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str = Field(default="logs/trading_bot.log", description="Log file path")

    @model_validator(mode="after")
    def _validate_trailing_stop(self) -> "Settings":
        """Reject a trailing stop that would fill the instant it is armed.

        The stop is raised to `trailing_stop_lock_pct` above entry once price
        reaches `trailing_stop_trigger_pct` above entry. If lock >= trigger, the
        new stop sits at or above the price that just armed it, so the very next
        check sells - turning the feature into "exit at the trigger", which is
        a take-profit and not what anyone configuring a trailing stop wants.
        """
        if self.trailing_stop_trigger_pct < 0 or self.trailing_stop_lock_pct < 0:
            raise ValueError("trailing stop percentages cannot be negative")
        if self.trailing_stop_trigger_pct == 0:
            return self
        if self.trailing_stop_lock_pct >= self.trailing_stop_trigger_pct:
            raise ValueError(
                "trailing_stop_lock_pct must be below trailing_stop_trigger_pct, otherwise "
                "the raised stop would sit at or above the price that armed it and fill "
                "immediately"
            )
        return self

    @model_validator(mode="after")
    def _validate_take_profit(self) -> "Settings":
        if self.take_profit_pct < 0:
            raise ValueError("take_profit_pct cannot be negative")
        if not (0 < self.take_profit_exit_pct <= 100):
            raise ValueError("take_profit_exit_pct must be between 0 (exclusive) and 100")
        return self

    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self.trading_mode == TradingMode.PAPER

    @property
    def effective_stop_enforcement(self) -> StopEnforcement:
        """The enforcement mechanism actually in force, accounting for paper trading.

        OFF short-circuits everything. Otherwise PaperTradingSimulator has no
        resting orders, so a stop can only be acted on by the bot's own polling
        there. Reading this rather than `stop_enforcement` directly is what
        guarantees the two mechanisms never run at once: paper never resolves to
        NATIVE regardless of configuration.
        """
        if self.stop_enforcement is StopEnforcement.OFF:
            return StopEnforcement.OFF
        if self.is_paper_trading:
            return StopEnforcement.POLL
        return self.stop_enforcement


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
