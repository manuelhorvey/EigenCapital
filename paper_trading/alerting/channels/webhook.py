"""Generic JSON webhook alert channel (Slack, Discord, Teams, etc.)."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Any

from paper_trading.alerting.channel import Alert, Channel, Severity

logger = logging.getLogger("quorrin.alerting.webhook")

_COLOR_MAP: dict[Severity, str] = {
    Severity.CRITICAL: "danger",
    Severity.WARNING: "warning",
    Severity.INFO: "good",
}


class WebhookChannel(Channel):
    """Sends alerts to an arbitrary JSON webhook endpoint.

    Templates the payload according to *format*:

    - ``"slack"``          — Slack ``attachments`` format
    - ``"discord"``        — Discord Embed format
    - ``"generic"``        — plain JSON with top-level keys
    """

    def __init__(self, url: str, format: str = "slack", min_interval: float = 10.0):
        self._url = url
        self._format = format
        self._min_interval = min_interval
        self._last_send: float = 0.0

    def send(self, alert: Alert) -> bool:
        now = time.monotonic()
        if now - self._last_send < self._min_interval:
            return False
        payload = self._build_payload(alert)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            ok = resp.status == 200
        except Exception as exc:
            logger.warning("Webhook POST failed: %s", exc)
            ok = False
        if ok:
            self._last_send = now
        return ok

    def _build_payload(self, alert: Alert) -> dict[str, Any]:
        if self._format == "slack":
            return self._slack_payload(alert)
        if self._format == "discord":
            return self._discord_payload(alert)
        return self._generic_payload(alert)

    def _generic_payload(self, alert: Alert) -> dict[str, Any]:
        return {
            "severity": alert.severity.value,
            "title": alert.title,
            "message": alert.message,
            "asset": alert.asset,
            "correlation_id": alert.correlation_id,
            "details": alert.details,
        }

    def _slack_payload(self, alert: Alert) -> dict[str, Any]:
        fields = []
        if alert.asset:
            fields.append({"title": "Asset", "value": alert.asset, "short": True})
        if alert.correlation_id:
            fields.append({"title": "Correlation ID", "value": alert.correlation_id, "short": True})
        for k, v in alert.details.items():
            fields.append({"title": k, "value": str(v), "short": True})
        return {
            "attachments": [
                {
                    "color": _COLOR_MAP.get(alert.severity, "good"),
                    "title": alert.title,
                    "text": alert.message,
                    "fields": fields,
                    "ts": int(time.time()),
                }
            ]
        }

    def _discord_payload(self, alert: Alert) -> dict[str, Any]:
        color_map = {Severity.CRITICAL: 0xFF0000, Severity.WARNING: 0xFFA500, Severity.INFO: 0x00FF00}
        embed = {
            "title": alert.title,
            "description": alert.message,
            "color": color_map.get(alert.severity, 0x00FF00),
            "fields": [{"name": k, "value": str(v), "inline": True} for k, v in alert.details.items()],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if alert.asset:
            embed["author"] = {"name": alert.asset}
        return {"embeds": [embed]}
