"""AlertManager — centralized dispatch to multiple alerting channels."""

from __future__ import annotations

import logging
import threading
from typing import Any

from paper_trading.alerting.channel import Alert, Channel, Severity
from paper_trading.logging.correlation import get_correlation_id

logger = logging.getLogger("eigencapital.alerting.manager")


class AlertManager:
    """Thread-safe alert dispatcher.

    Collects alerts and sends to every registered channel that matches the
    alert's severity threshold.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._channels: list[tuple[Severity, Channel]] = []

    def add_channel(self, channel: Channel, min_severity: Severity = Severity.WARNING) -> None:
        """Register *channel* to receive alerts at or above *min_severity*."""
        with self._lock:
            self._channels.append((min_severity, channel))

    def remove_channel(self, channel: Channel) -> None:
        with self._lock:
            self._channels[:] = [(s, c) for s, c in self._channels if c is not channel]

    @property
    def channel_count(self) -> int:
        with self._lock:
            return len(self._channels)

    def alert(
        self,
        severity: Severity,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
        asset: str | None = None,
    ) -> list[bool]:
        """Dispatch an alert. Returns list of send results (one per channel)."""
        cid = get_correlation_id()
        alert = Alert(
            severity=severity,
            title=title,
            message=message,
            details=details or {},
            asset=asset,
            correlation_id=cid or None,
        )
        results: list[bool] = []
        with self._lock:
            channels = list(self._channels)
        for threshold, channel in channels:
            if _severity_ge(severity, threshold):
                try:
                    ok = channel.send(alert)
                except Exception as exc:
                    logger.warning("Alert channel %s failed: %s", type(channel).__name__, exc)
                    ok = False
                results.append(ok)
                if not ok:
                    logger.debug("Alert channel %s returned failure", type(channel).__name__)
        return results

    def critical(self, title: str, message: str, **kwargs) -> list[bool]:
        return self.alert(Severity.CRITICAL, title, message, **kwargs)

    def warning(self, title: str, message: str, **kwargs) -> list[bool]:
        return self.alert(Severity.WARNING, title, message, **kwargs)

    def info(self, title: str, message: str, **kwargs) -> list[bool]:
        return self.alert(Severity.INFO, title, message, **kwargs)


def _severity_ge(a: Severity, b: Severity) -> bool:
    """True if *a* is at least as severe as *b*."""
    order = [Severity.INFO, Severity.WARNING, Severity.CRITICAL]
    return order.index(a) >= order.index(b)


# Global singleton
_alert_manager: AlertManager | None = None
_alert_manager_lock = threading.Lock()


def global_alert_manager() -> AlertManager:
    global _alert_manager
    if _alert_manager is None:
        with _alert_manager_lock:
            if _alert_manager is None:
                _alert_manager = AlertManager()
    return _alert_manager


def _reset_alert_manager() -> None:
    global _alert_manager
    with _alert_manager_lock:
        _alert_manager = None


def setup_alerting_from_config(config: dict | None = None) -> AlertManager:
    """Read alerting channel config and register channels on the global manager.

    Called once at engine startup.  Idempotent — channels are only added
    once.  Environment variables take precedence over YAML values::

        PAGERDUTY_ROUTING_KEY  →  alerting.channels.pagerduty.routing_key
        ALERTING_WEBHOOK_URL   →  alerting.channels.webhook.url
    """
    import os

    from paper_trading.alerting.channels.pagerduty import PagerDutyChannel
    from paper_trading.alerting.channels.webhook import WebhookChannel

    mgr = global_alert_manager()
    if mgr.channel_count > 0:
        return mgr  # already initialized

    if config is None:
        try:
            from paper_trading.config_manager import get_config

            config = get_config()
        except Exception:
            config = {}
    alerting_cfg = config.get("alerting", {}) if isinstance(config, dict) else getattr(config, "alerting", None) or {}
    channels_cfg = alerting_cfg.get("channels", {}) if isinstance(alerting_cfg, dict) else {}

    # PagerDuty
    pd_cfg = channels_cfg.get("pagerduty", {}) if isinstance(channels_cfg, dict) else {}
    pd_key = os.environ.get("PAGERDUTY_ROUTING_KEY") or pd_cfg.get("routing_key", "")
    if pd_cfg.get("enabled", False) and pd_key:
        mgr.add_channel(
            PagerDutyChannel(routing_key=pd_key, min_interval=pd_cfg.get("min_interval", 30.0)),
        )
        logger.info("Alerting: PagerDuty channel enabled")

    # Generic webhook
    wh_cfg = channels_cfg.get("webhook", {}) if isinstance(channels_cfg, dict) else {}
    wh_url = os.environ.get("ALERTING_WEBHOOK_URL") or wh_cfg.get("url", "")
    if wh_cfg.get("enabled", False) and wh_url:
        mgr.add_channel(
            WebhookChannel(
                url=wh_url,
                format=wh_cfg.get("format", "slack"),
                min_interval=wh_cfg.get("min_interval", 10.0),
            ),
        )
        logger.info("Alerting: Webhook channel enabled")

    return mgr
