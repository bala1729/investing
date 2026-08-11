"""SMS alerting via Twilio's REST API.

Deliberately speaks HTTP directly rather than pulling in the `twilio` SDK: the
send is a single authenticated POST, and every dependency added here has to be
carried through pip-audit in CI (which already went red once this project on
transitive CVEs).

Disabled unless fully configured. A half-configured notifier silently does
nothing rather than raising, because an alerting failure must never be able to
take down the trading loop that it is supposed to be watching.

Credentials and the destination number live in .env only - never in code, never
in .env.example. This repository is public.
"""

from typing import Any

import aiohttp
from loguru import logger

from src.config import Settings, get_settings

_TWILIO_ENDPOINT = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

# SMS segments at 160 characters; keep alerts inside one segment where possible.
MAX_SMS_LENGTH = 320


class SmsNotifier:
    """Sends short operational alerts to a single destination number.

    Every failure path is swallowed and logged. The caller is a trading loop:
    it must not crash, retry forever, or block on a notification provider being
    slow or down.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        """Whether every credential needed to actually send is present."""
        s = self._settings
        return bool(
            s.sms_alerts_enabled
            and s.twilio_account_sid
            and s.twilio_api_key_sid
            and s.twilio_api_key_secret
            and s.twilio_from_number
            and s.alert_phone_number
        )

    async def send(self, message: str) -> bool:
        """Send `message`, returning whether it was accepted by the provider.

        Never raises. Returns False when unconfigured, so callers can treat
        "alerting is off" and "alerting failed" identically - neither is a
        reason to interrupt trading.
        """
        if not self.is_configured:
            return False

        body = message.strip()
        if len(body) > MAX_SMS_LENGTH:
            body = body[: MAX_SMS_LENGTH - 1] + "…"

        s = self._settings
        url = _TWILIO_ENDPOINT.format(sid=s.twilio_account_sid)
        payload = {
            "To": s.alert_phone_number,
            "From": s.twilio_from_number,
            "Body": body,
        }
        # An API Key SID/secret pair, not the account's own auth token - scoped and
        # revocable independently of the account credential. The account SID still
        # namespaces the URL above; it just isn't the auth credential here.
        # encode_basic_auth rather than aiohttp.BasicAuth: the latter is
        # deprecated and removed in aiohttp 4.0.
        headers = {
            "Authorization": aiohttp.encode_basic_auth(
                s.twilio_api_key_sid, s.twilio_api_key_secret
            )
        }

        try:
            timeout = aiohttp.ClientTimeout(total=s.sms_timeout_seconds)
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(url, data=payload, headers=headers) as response,
            ):
                if response.status >= 400:
                    detail = await response.text()
                    logger.error(
                        f"SMS alert rejected ({response.status}): {detail[:200]}"
                    )
                    return False
                logger.debug(f"SMS alert sent: {body[:60]}")
                return True
        except (TimeoutError, aiohttp.ClientError, OSError):
            # Logged, not raised: the trading loop must survive a flaky provider.
            logger.exception("SMS alert failed to send")
            return False


def format_fill_alert(
    action: str,
    symbol: str,
    side: str,
    amount: Any,
    price: Any,
    strategy: str,
    pnl: Any | None = None,
    is_paper: bool = True,
) -> str:
    """Build a one-line fill alert.

    Leads with PAPER/LIVE because the two are indistinguishable from the text
    otherwise, and mistaking one for the other is the expensive error.
    """
    mode = "PAPER" if is_paper else "LIVE"
    line = f"[{mode}] {action} {side.upper()} {amount} {symbol} @ {price}"
    if pnl is not None:
        line += f" | P&L {pnl}"
    return f"{line} | {strategy}"
