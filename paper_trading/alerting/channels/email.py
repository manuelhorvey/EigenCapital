"""Email alert channel — sends alerts via SMTP as a fallback when other
channels (PagerDuty, webhook) are unavailable.

Configuration (environment variables):
    ALERTING_SMTP_HOST     (default: localhost)
    ALERTING_SMTP_PORT     (default: 25)
    ALERTING_SMTP_USER     (optional: for authenticated SMTP)
    ALERTING_SMTP_PASSWORD (optional)
    ALERTING_SMTP_FROM     (default: eigencapital@localhost)
    ALERTING_SMTP_TO       (comma-separated recipient list, required)

Usage:
    from paper_trading.alerting.channels.email import EmailChannel

    channel = EmailChannel(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        from_addr="alerts@eigencapital.local",
        to_addrs=["ops@example.com"],
        use_tls=True,
    )
    channel.send(alert)
"""

from __future__ import annotations

import logging
import os
import smtplib
import time
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from typing import Any

from paper_trading.alerting.channel import Alert, Channel

logger = logging.getLogger("eigencapital.alerting.email")


@dataclass
class EmailConfig:
    """SMTP configuration for email alerting."""

    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    from_addr: str = "eigencapital@localhost"
    to_addrs: list[str] = field(default_factory=list)
    use_tls: bool = False
    min_interval: float = 60.0  # seconds between identical alerts


class EmailChannel(Channel):
    """SMTP-based alert channel. Acts as a fallback when primary channels fail.

    Thread-safe via per-instance lock for rate limiting.
    """

    def __init__(self, config: EmailConfig | None = None) -> None:
        self._config = config or self._from_env()
        self._last_send: dict[str, float] = {}
        self._lock = __import__("threading").Lock()

    @staticmethod
    def _from_env() -> EmailConfig:
        """Build EmailConfig from environment variables."""
        to_str = os.environ.get("ALERTING_SMTP_TO", "")
        to_addrs = [a.strip() for a in to_str.split(",") if a.strip()] if to_str else []
        return EmailConfig(
            smtp_host=os.environ.get("ALERTING_SMTP_HOST", "localhost"),
            smtp_port=int(os.environ.get("ALERTING_SMTP_PORT", "25")),
            smtp_user=os.environ.get("ALERTING_SMTP_USER", ""),
            smtp_password=os.environ.get("ALERTING_SMTP_PASSWORD", ""),
            from_addr=os.environ.get("ALERTING_SMTP_FROM", "eigencapital@localhost"),
            to_addrs=to_addrs,
            use_tls=os.environ.get("ALERTING_SMTP_TLS", "").lower() in ("1", "true", "yes"),
        )

    def _rate_limit_key(self, alert: Alert) -> str:
        """Build a rate-limit key based on alert title (dedup similar alerts)."""
        return f"{alert.severity.value}:{alert.title}"

    def send(self, alert: Alert) -> bool:
        """Send an alert email. Returns True on success."""
        if not self._config.to_addrs:
            logger.debug("Email channel: no recipients configured, skipping")
            return False

        # Rate limiting
        now = time.monotonic()
        rl_key = self._rate_limit_key(alert)
        with self._lock:
            last = self._last_send.get(rl_key, 0.0)
            if now - last < self._config.min_interval:
                logger.debug("Email channel: rate-limited alert '%s'", alert.title)
                return True  # Silent success — alert was already sent recently
            self._last_send[rl_key] = now

        try:
            body = self._format_alert(alert)
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = f"[EigenCapital] {alert.severity.value}: {alert.title}"
            msg["From"] = self._config.from_addr
            msg["To"] = ", ".join(self._config.to_addrs)
            msg["X-Correlation-ID"] = alert.correlation_id or ""

            with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port, timeout=10) as server:
                if self._config.use_tls:
                    server.starttls()
                if self._config.smtp_user:
                    server.login(self._config.smtp_user, self._config.smtp_password)
                server.sendmail(self._config.from_addr, self._config.to_addrs, msg.as_string())

            logger.debug(
                "Email alert sent: %s to %d recipient(s)",
                alert.title,
                len(self._config.to_addrs),
            )
            return True

        except (smtplib.SMTPException, OSError, TimeoutError, ConnectionError) as e:
            logger.warning("Email channel failed for alert '%s': %s", alert.title, e)
            return False

    @staticmethod
    def _format_alert(alert: Alert) -> str:
        """Format an Alert into a plain-text email body."""
        lines = [
            f"Severity: {alert.severity.value}",
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
            f"Asset: {alert.asset or 'N/A'}",
            f"Correlation ID: {alert.correlation_id or 'N/A'}",
            "",
            alert.message,
        ]
        if alert.details:
            lines.extend(["", "Details:"])
            for k, v in alert.details.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)


def create_email_channel_from_config(config: dict[str, Any] | None = None) -> EmailChannel | None:
    """Create an EmailChannel from the alerting config or environment variables.

    Returns None if no email configuration is found (no-op fallback).
    """
    # Check env vars first
    if os.environ.get("ALERTING_SMTP_TO"):
        return EmailChannel()

    if config:
        email_cfg = config.get("email", {}) if isinstance(config, dict) else {}
        if email_cfg.get("enabled", False) and email_cfg.get("to_addrs"):
            return EmailChannel(
                EmailConfig(
                    smtp_host=email_cfg.get("smtp_host", "localhost"),
                    smtp_port=int(email_cfg.get("smtp_port", 25)),
                    smtp_user=email_cfg.get("smtp_user", ""),
                    smtp_password=email_cfg.get("smtp_password", ""),
                    from_addr=email_cfg.get("from_addr", "eigencapital@localhost"),
                    to_addrs=email_cfg.get("to_addrs", []),
                    use_tls=email_cfg.get("use_tls", False),
                )
            )

    return None
