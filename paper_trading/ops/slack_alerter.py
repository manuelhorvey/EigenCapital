"""
WAL-tailing Slack alert daemon.

Reacts to halt, drawdown, and engine-down events from the engine's WAL
and sends formatted alerts to a Slack webhook.  Stateless, independent process —
no engine modifications required.

Usage:
    SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... \\
    PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/slack_alerter.py
"""

import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

WAL_DIR = Path("data/live/wal")
STATE_PATH = Path("data/live/state.json")
ALERT_STATE_PATH = Path("data/live/alert_state.json")

CHECK_INTERVAL = 5  # seconds between WAL polls
STATE_CHECK_INTERVAL = 60  # seconds between state.json drawdown checks
ENGINE_STALE_SECONDS = 120  # no WAL event in this window = engine likely down
COOLDOWN_HALT = 300  # per-asset halt cooldown (5 min)
COOLDOWN_EMERGENCY = 600  # emergency halt cooldown (10 min)
DRAWDOWN_THRESHOLD = -0.10  # portfolio drawdown alert threshold (10%)
CONCENTRATION_HEARTBEAT_INTERVAL = 3600  # heartbeat every hour when skew sustained


def _send_slack(webhook_url: str, message: dict) -> bool:
    data = json.dumps(message).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200
    except Exception as exc:
        logger.error("Slack POST failed: %s", exc)
        return False


def _load_alert_state() -> dict:
    if ALERT_STATE_PATH.exists():
        try:
            return json.loads(ALERT_STATE_PATH.read_text())
        except Exception:
            logger.warning("Corrupt alert state, resetting")
    return {
        "wal_position": 0,
        "cooldowns": {},
        "last_state_drawdown": None,
        "concentration_state": "below_threshold",
        "concentration_last_skew": 0.0,
        "concentration_dominant_side": "none",
        "concentration_alert_time": None,
        "concentration_heartbeat_due": None,
    }


def _save_alert_state(state: dict) -> None:
    ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STATE_PATH.write_text(json.dumps(state, indent=2))


def _check_drawdown() -> float | None:
    try:
        if not STATE_PATH.exists():
            return None
        data = json.loads(STATE_PATH.read_text())
        portfolio = data.get("portfolio", {})
        pv = portfolio.get("portfolio_value")
        peak = portfolio.get("peak_value")
        if pv is not None and peak and peak > 0:
            return (pv / peak) - 1
    except Exception:
        pass
    return None


def _build_blocks(header_text: str, emoji: str, fields: list[dict], context: str | None = None) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {header_text}"},
        },
    ]
    if fields:
        blocks.append({"type": "section", "fields": fields})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": context or f"QuantForge · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                },
            ],
        }
    )
    return blocks


class SlackAlerter:
    def __init__(self, webhook_url: str, source: str = "engine"):
        self.webhook_url = webhook_url
        self.wal_path = WAL_DIR / f"{source}.jsonl"
        self.state = _load_alert_state()
        self._last_emergency_alert = 0.0
        self._last_drawdown_alert = 0.0
        self._last_state_check = 0.0
        self._last_wal_event_time = time.time()
        self._engine_down_sent = False

        if not ALERT_STATE_PATH.exists() and self.wal_path.exists():
            self.state["wal_position"] = self.wal_path.stat().st_size
            _save_alert_state(self.state)

    def run(self) -> None:
        logger.info("Slack alerter started, tailing %s", self.wal_path)
        while True:
            try:
                self._poll_wal()
                self._check_engine_stale()
                self._check_state_if_due()
                time.sleep(CHECK_INTERVAL)
            except KeyboardInterrupt:
                logger.info("Shutting down")
                break
            except Exception:
                logger.exception("Error in main loop")
                time.sleep(CHECK_INTERVAL)

    def _poll_wal(self) -> None:
        if not self.wal_path.exists():
            return
        with open(self.wal_path) as f:
            f.seek(self.state["wal_position"])
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._last_wal_event_time = time.time()
                self._process_event(event)
            self.state["wal_position"] = f.tell()
        _save_alert_state(self.state)

    def _process_event(self, event: dict) -> None:
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        if event_type == "state_committed":
            self._handle_state_committed(payload)
        elif event_type == "position_concentration":
            self._handle_concentration(payload)

    def _handle_state_committed(self, payload: dict) -> None:
        actors = payload.get("actors", {})
        emergency = payload.get("emergency_halt", False)
        now = time.time()
        any_sent = False

        for asset, info in actors.items():
            if info.get("health") == "HALTED":
                key = f"halt:{asset}"
                last = self.state["cooldowns"].get(key, 0)
                if now - last >= COOLDOWN_HALT:
                    self.state["cooldowns"][key] = now
                    any_sent = True
                    self._send_asset_halted(asset, info)

        if emergency and now - self._last_emergency_alert >= COOLDOWN_EMERGENCY:
            self._last_emergency_alert = now
            any_sent = True
            self._send_emergency_halt(actors)

        if any_sent:
            _save_alert_state(self.state)

    def _handle_concentration(self, payload: dict) -> None:
        skew = payload.get("skew", 0.0)
        threshold = payload.get("threshold", 0.75)
        alert = payload.get("alert", False)
        dominant_side = payload.get("dominant_side", "none")

        prev_state = self.state.get("concentration_state", "below_threshold")
        current_state = "above_threshold" if alert else "below_threshold"
        now = time.time()

        if prev_state != current_state:
            self.state["concentration_state"] = current_state
            self.state["concentration_last_skew"] = skew
            self.state["concentration_dominant_side"] = dominant_side
            self.state["concentration_alert_time"] = now
            self.state["concentration_heartbeat_due"] = now + CONCENTRATION_HEARTBEAT_INTERVAL

            if current_state == "above_threshold":
                self._send_concentration_alert(skew, threshold, dominant_side, alert_type="onset")
            else:
                self._send_concentration_alert(skew, threshold, dominant_side, alert_type="clear")
            _save_alert_state(self.state)

        elif current_state == "above_threshold":
            heartbeat_due = self.state.get("concentration_heartbeat_due")
            if heartbeat_due is not None and now >= heartbeat_due:
                self.state["concentration_heartbeat_due"] = now + CONCENTRATION_HEARTBEAT_INTERVAL
                self.state["concentration_last_skew"] = skew
                self._send_concentration_alert(skew, threshold, dominant_side, alert_type="heartbeat")
                _save_alert_state(self.state)

    def _send_concentration_alert(self, skew: float, threshold: float, dominant_side: str, alert_type: str) -> None:
        pct = round(skew * 100, 1)
        thresh_pct = round(threshold * 100, 0)

        if alert_type == "onset":
            header = f"Skew {pct}% — Threshold Crossed"
            title = f"⚠️ Position Concentration: {pct}% {dominant_side}"
            body = f"Portfolio skew crossed *{thresh_pct:.0f}%* threshold: *{pct}%* on the {dominant_side} side."
        elif alert_type == "clear":
            header = "Skew Cleared"
            title = "✅ Position Concentration Normalized"
            body = f"Portfolio skew has returned below *{thresh_pct:.0f}%* threshold."
        elif alert_type == "heartbeat":
            header = f"Skew Sustained {pct}%"
            title = f"⚠️ Position Concentration Sustained: {pct}% {dominant_side}"
            body = (
                f"Portfolio skew has been above *{thresh_pct:.0f}%* for over an hour "
                f"(currently *{pct}%* {dominant_side})."
            )

        msg = {
            "text": title,
            "blocks": _build_blocks(
                header,
                "⚠️",
                [
                    {"type": "mrkdwn", "text": body},
                    {"type": "mrkdwn", "text": f"*Threshold:* {thresh_pct:.0f}%" if dominant_side != "none" else ""},
                ],
            ),
        }
        if _send_slack(self.webhook_url, msg):
            logger.info("Concentration %s alert sent (skew=%.1f%%)", alert_type, pct)
        else:
            logger.warning("Concentration %s alert FAILED (skew=%.1f%%)", alert_type, pct)

    def _send_asset_halted(self, asset: str, info: dict) -> None:
        msg = {
            "text": f"Asset halted: {asset}",
            "blocks": _build_blocks(
                f"{asset} HALTED",
                "🚫",
                [
                    {"type": "mrkdwn", "text": f"*Asset:* {asset}"},
                    {"type": "mrkdwn", "text": f"*Health:* {info.get('health', '?')}"},
                    {"type": "mrkdwn", "text": f"*Cycle:* {info.get('cycle_id', '?')}"},
                    {"type": "mrkdwn", "text": f"*Failures:* {info.get('consecutive_failures', 0)}"},
                ],
            ),
        }
        if _send_slack(self.webhook_url, msg):
            logger.info("Halt alert sent for %s", asset)
        else:
            logger.warning("Halt alert FAILED for %s", asset)

    def _send_emergency_halt(self, actors: dict) -> None:
        halted = [a for a, i in actors.items() if i.get("health") == "HALTED"]
        count = len(halted)
        desc = ", ".join(halted[:5])
        if count > 5:
            desc += f" +{count - 5} more"
        msg = {
            "text": f"EMERGENCY HALT — {count} asset(s) halted",
            "blocks": _build_blocks(
                f"EMERGENCY HALT ({count})",
                "🚨",
                [{"type": "mrkdwn", "text": f"Circuit breaker triggered. Halted: {desc}"}],
            ),
        }
        if _send_slack(self.webhook_url, msg):
            logger.info("Emergency halt alert sent")
        else:
            logger.warning("Emergency halt alert FAILED")

    def _check_engine_stale(self) -> None:
        idle = time.time() - self._last_wal_event_time
        if idle > ENGINE_STALE_SECONDS and not self._engine_down_sent:
            self._engine_down_sent = True
            self._send_engine_stale(idle)
        elif idle <= ENGINE_STALE_SECONDS and self._engine_down_sent:
            self._engine_down_sent = False

    def _send_engine_stale(self, idle_seconds: float) -> None:
        minutes = int(idle_seconds // 60)
        msg = {
            "text": f"Engine may be down — no WAL activity for {minutes}m",
            "blocks": _build_blocks(
                "Engine Stale",
                "⚪",
                [
                    {
                        "type": "mrkdwn",
                        "text": f"No WAL events for *{minutes} minute(s)*. Engine may be down or stalled.",
                    },
                ],
            ),
        }
        if _send_slack(self.webhook_url, msg):
            logger.warning("Engine stale alert sent (%d min idle)", minutes)
        else:
            logger.warning("Engine stale alert FAILED")

    def _check_state_if_due(self) -> None:
        now = time.time()
        if now - self._last_state_check < STATE_CHECK_INTERVAL:
            return
        self._last_state_check = now

        dd = _check_drawdown()
        if dd is None:
            return

        prev = self.state.get("last_state_drawdown")
        if dd <= DRAWDOWN_THRESHOLD and (prev is None or dd < prev):
            self.state["last_state_drawdown"] = dd
            _save_alert_state(self.state)
            self._send_drawdown_alert(dd)
        elif dd > DRAWDOWN_THRESHOLD and prev is not None:
            self.state["last_state_drawdown"] = None
            _save_alert_state(self.state)

    def _send_drawdown_alert(self, drawdown: float) -> None:
        pct = round(drawdown * 100, 1)
        msg = {
            "text": f"Portfolio drawdown: {pct}%",
            "blocks": _build_blocks(
                f"Drawdown {pct}%",
                "📉",
                [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"Portfolio drawdown reached *{pct}%* (threshold: {abs(DRAWDOWN_THRESHOLD * 100):.0f}%)."
                        ),
                    },
                ],
            ),
        }
        if _send_slack(self.webhook_url, msg):
            logger.info("Drawdown alert sent (%.1f%%)", pct)
        else:
            logger.warning("Drawdown alert FAILED")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set; slack_alerter disabled")
        return
    SlackAlerter(webhook_url).run()


if __name__ == "__main__":
    main()
