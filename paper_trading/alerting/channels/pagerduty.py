"""PagerDuty Events API v2 alert channel."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any

from paper_trading.alerting.channel import Alert, Channel, Severity

logger = logging.getLogger("eigencapital.alerting.pagerduty")

_EVENT_API = "https://events.pagerduty.com/v2/enqueue"

_SEVERITY_MAP: dict[Severity, str] = {
    Severity.CRITICAL: "critical",
    Severity.WARNING: "warning",
    Severity.INFO: "info",
}


class PagerDutyChannel(Channel):
    """PagerDuty Events API v2 channel.

    Requires a *routing_key* (integration key for the PagerDuty service).
    Optionally accepts a *dedup_key* template — defaults to asset-based dedup.
    """

    def __init__(
        self,
        routing_key: str,
        dedup_key_template: str = "eigencapital/{asset}",
        min_interval: float = 30.0,
    ):
        self._routing_key = routing_key
        self._dedup_key_template = dedup_key_template
        self._min_interval = min_interval
        self._last_send: float = 0.0

    def send(self, alert: Alert) -> bool:
        now = time.monotonic()
        if now - self._last_send < self._min_interval:
            return False
        payload = self._build_payload(alert)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            _EVENT_API,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            ok = resp.status == 202
        except Exception as exc:
            logger.warning("PagerDuty POST failed: %s", exc)
            ok = False
        if ok:
            self._last_send = now
        return ok

    def _build_payload(self, alert: Alert) -> dict[str, Any]:
        return {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": self._dedup_key_template.format(asset=alert.asset or "portfolio"),
            "payload": {
                "summary": f"{alert.title}: {alert.message}",
                "severity": _SEVERITY_MAP.get(alert.severity, "info"),
                "source": "eigencapital",
                "component": alert.asset or "portfolio",
                "group": "paper-trading",
                "class": alert.severity.value.lower(),
                "custom_details": alert.details,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }

    def resolve(self, asset: str | None = None) -> bool:
        """Send a resolve event for the given asset dedup key."""
        dedup_key = self._dedup_key_template.format(asset=asset or "portfolio")
        payload = {
            "routing_key": self._routing_key,
            "event_action": "resolve",
            "dedup_key": dedup_key,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            _EVENT_API,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.status == 202
        except Exception as exc:
            logger.warning("PagerDuty resolve failed: %s", exc)
            return False
