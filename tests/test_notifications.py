"""Tests for SMS alerting.

The governing rule for every test here: alerting must never be able to break
trading. A notifier that raises, blocks, or returns a surprising type would put
a trading loop at the mercy of an SMS provider.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from src.config import Settings
from src.notifications import SmsNotifier, format_fill_alert
from src.notifications.sms import MAX_SMS_LENGTH


def configured(**overrides: object) -> Settings:
    base = {
        "sms_alerts_enabled": True,
        "twilio_account_sid": "AC_test",
        "twilio_auth_token": "token",
        "twilio_from_number": "+15550000000",
        "alert_phone_number": "+15550000001",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


class TestIsConfigured:
    def test_disabled_by_default(self) -> None:
        assert SmsNotifier(Settings(_env_file=None)).is_configured is False

    def test_fully_configured(self) -> None:
        assert SmsNotifier(configured()).is_configured is True

    @pytest.mark.parametrize(
        "missing",
        ["twilio_account_sid", "twilio_auth_token", "twilio_from_number", "alert_phone_number"],
    )
    def test_any_missing_credential_disables_it(self, missing: str) -> None:
        """Half-configured must mean off, not a runtime failure mid-trade."""
        assert SmsNotifier(configured(**{missing: ""})).is_configured is False

    def test_flag_off_disables_it_even_when_credentials_are_present(self) -> None:
        assert SmsNotifier(configured(sms_alerts_enabled=False)).is_configured is False


class TestSend:
    async def test_unconfigured_send_is_a_silent_no_op(self) -> None:
        assert await SmsNotifier(Settings(_env_file=None)).send("hello") is False

    async def test_successful_send_posts_to_twilio(self) -> None:
        notifier = SmsNotifier(configured())
        response = AsyncMock()
        response.status = 201
        with patch("aiohttp.ClientSession.post") as post:
            post.return_value.__aenter__.return_value = response
            assert await notifier.send("hello") is True
            payload = post.call_args.kwargs["data"]
        headers = post.call_args.kwargs["headers"]
        assert headers["Authorization"].startswith("Basic ")
        assert payload["To"] == "+15550000001"
        assert payload["From"] == "+15550000000"
        assert payload["Body"] == "hello"

    async def test_provider_rejection_returns_false_without_raising(self) -> None:
        notifier = SmsNotifier(configured())
        response = AsyncMock()
        response.status = 401
        response.text.return_value = "unauthorized"
        with patch("aiohttp.ClientSession.post") as post:
            post.return_value.__aenter__.return_value = response
            assert await notifier.send("hello") is False

    async def test_network_failure_returns_false_without_raising(self) -> None:
        """A dead provider must not propagate an exception into the trading loop."""
        notifier = SmsNotifier(configured())
        with patch("aiohttp.ClientSession.post", side_effect=aiohttp.ClientError("boom")):
            assert await notifier.send("hello") is False

    async def test_timeout_returns_false_without_raising(self) -> None:
        notifier = SmsNotifier(configured())
        with patch("aiohttp.ClientSession.post", side_effect=TimeoutError):
            assert await notifier.send("hello") is False

    async def test_overlong_message_is_truncated(self) -> None:
        notifier = SmsNotifier(configured())
        response = AsyncMock()
        response.status = 201
        with patch("aiohttp.ClientSession.post") as post:
            post.return_value.__aenter__.return_value = response
            await notifier.send("x" * (MAX_SMS_LENGTH + 500))
            body = post.call_args.kwargs["data"]["Body"]
        assert len(body) == MAX_SMS_LENGTH
        assert body.endswith("…")


class TestFormatFillAlert:
    def test_entry_alert_leads_with_mode(self) -> None:
        """PAPER and LIVE are otherwise indistinguishable, and confusing them is costly."""
        text = format_fill_alert("ENTRY", "SOL/USD", "buy", "6.79", Decimal("73.65"), "rsi")
        assert text.startswith("[PAPER] ENTRY BUY")
        assert "SOL/USD @ 73.65" in text
        assert "rsi" in text

    def test_live_exit_alert_includes_pnl(self) -> None:
        text = format_fill_alert(
            "EXIT", "SOL/USD", "sell", "6.79", Decimal("74.20"), "rsi",
            pnl="+3.73", is_paper=False,
        )
        assert text.startswith("[LIVE] EXIT SELL")
        assert "P&L +3.73" in text

    def test_entry_alert_omits_pnl(self) -> None:
        assert "P&L" not in format_fill_alert("ENTRY", "SOL/USD", "buy", "1", 1, "rsi")
