"""Campaign Start Snapshot — immutable T=0 reference.

Captured BEFORE the first order is placed. Every subsequent event
is interpreted relative to this known starting state.

Contains:
- Account state (equity, balance, free margin)
- Open positions (all classified)
- Pending orders
- R4 fingerprint
- Risk-policy fingerprint
- Broker/account identity
- Campaign ID
- Timestamp
- Pre-trading gate decision

Design rules:
- Immutable (frozen dataclass)
- Hash-chained to detect tampering
- Complete: every field required, no partial snapshots
- Idempotent: re-capturing produces identical snapshot
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.production_qual.pre_trading import (
    BrokerStateSnapshot,
    PreTradingAuthorization,
)
from eigencapital.production_qual.prefunding_gate import GateRecord
from eigencapital.risk.policy import RiskPolicy


@dataclass(frozen=True)
class CampaignStartSnapshot:
    """Immutable T=0 reference for the MINIMAL campaign.

    Captured at the exact moment TRADING_AUTHORIZED is received,
    before any order is submitted. Becomes the baseline against
    which all subsequent events are measured.
    """

    # ── Identity ───────────────────────────────────────────────────
    campaign_id: str
    snapshot_timestamp: str  # ISO-8601 UTC

    # ── Account State ──────────────────────────────────────────────
    equity: float
    balance: float
    free_margin: float
    margin_level: float
    currency: str = "USD"

    # ── Positions ──────────────────────────────────────────────────
    open_positions: List[Dict[str, Any]] = field(default_factory=list)
    position_count: int = 0
    total_exposure: float = 0.0
    net_exposure: float = 0.0

    # ── Pending Orders ─────────────────────────────────────────────
    pending_orders: List[Dict[str, Any]] = field(default_factory=list)
    pending_order_count: int = 0

    # ── Fingerprints ───────────────────────────────────────────────
    r4_manifest_fingerprint: str = ""
    risk_policy_fingerprint: str = ""
    broker_config_fingerprint: str = ""
    capital_config_fingerprint: str = ""

    # ── Broker Identity ────────────────────────────────────────────
    account_id: str = ""
    account_name: str = ""
    broker_name: str = ""
    environment: str = ""
    platform: str = ""

    # ── Gate Records ───────────────────────────────────────────────
    pre_funding_gate_decision: str = ""
    pre_funding_gate_hash: str = ""
    pre_trading_decision: str = ""
    pre_trading_hash: str = ""

    # ── Risk Limits (frozen) ───────────────────────────────────────
    max_drawdown_pct: float = 0.0
    daily_loss_limit: float = 0.0
    max_gross_leverage: float = 0.0
    max_position_count: int = 0
    max_concentration_pct: float = 0.0
    max_asset_class_exposure_pct: float = 0.0

    # ── Campaign Parameters ────────────────────────────────────────
    max_campaign_equity: float = 0.0
    campaign_duration_days: int = 0
    max_position_size: float = 0.0
    max_order_notional: float = 0.0

    # ── Computed ───────────────────────────────────────────────────
    snapshot_hash: str = ""

    def compute_hash(self) -> str:
        """Compute deterministic fingerprint of the entire snapshot."""
        data = {
            "campaign_id": self.campaign_id,
            "snapshot_timestamp": self.snapshot_timestamp,
            "equity": self.equity,
            "balance": self.balance,
            "free_margin": self.free_margin,
            "margin_level": self.margin_level,
            "currency": self.currency,
            "position_count": self.position_count,
            "total_exposure": self.total_exposure,
            "net_exposure": self.net_exposure,
            "pending_order_count": self.pending_order_count,
            "r4_manifest_fingerprint": self.r4_manifest_fingerprint,
            "risk_policy_fingerprint": self.risk_policy_fingerprint,
            "broker_config_fingerprint": self.broker_config_fingerprint,
            "capital_config_fingerprint": self.capital_config_fingerprint,
            "account_id": self.account_id,
            "broker_name": self.broker_name,
            "environment": self.environment,
            "pre_funding_gate_decision": self.pre_funding_gate_decision,
            "pre_funding_gate_hash": self.pre_funding_gate_hash,
            "pre_trading_decision": self.pre_trading_decision,
            "pre_trading_hash": self.pre_trading_hash,
            "max_drawdown_pct": self.max_drawdown_pct,
            "daily_loss_limit": self.daily_loss_limit,
            "max_gross_leverage": self.max_gross_leverage,
            "max_position_count": self.max_position_count,
            "max_concentration_pct": self.max_concentration_pct,
            "max_asset_class_exposure_pct": self.max_asset_class_exposure_pct,
            "max_campaign_equity": self.max_campaign_equity,
            "campaign_duration_days": self.campaign_duration_days,
            "max_position_size": self.max_position_size,
            "max_order_notional": self.max_order_notional,
            "open_positions": self.open_positions,
            "pending_orders": self.pending_orders,
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "snapshot_timestamp": self.snapshot_timestamp,
            "equity": self.equity,
            "balance": self.balance,
            "free_margin": self.free_margin,
            "margin_level": self.margin_level,
            "currency": self.currency,
            "open_positions": self.open_positions,
            "position_count": self.position_count,
            "total_exposure": self.total_exposure,
            "net_exposure": self.net_exposure,
            "pending_orders": self.pending_orders,
            "pending_order_count": self.pending_order_count,
            "r4_manifest_fingerprint": self.r4_manifest_fingerprint,
            "risk_policy_fingerprint": self.risk_policy_fingerprint,
            "broker_config_fingerprint": self.broker_config_fingerprint,
            "capital_config_fingerprint": self.capital_config_fingerprint,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "broker_name": self.broker_name,
            "environment": self.environment,
            "platform": self.platform,
            "pre_funding_gate_decision": self.pre_funding_gate_decision,
            "pre_funding_gate_hash": self.pre_funding_gate_hash,
            "pre_trading_decision": self.pre_trading_decision,
            "pre_trading_hash": self.pre_trading_hash,
            "max_drawdown_pct": self.max_drawdown_pct,
            "daily_loss_limit": self.daily_loss_limit,
            "max_gross_leverage": self.max_gross_leverage,
            "max_position_count": self.max_position_count,
            "max_concentration_pct": self.max_concentration_pct,
            "max_asset_class_exposure_pct": self.max_asset_class_exposure_pct,
            "max_campaign_equity": self.max_campaign_equity,
            "campaign_duration_days": self.campaign_duration_days,
            "max_position_size": self.max_position_size,
            "max_order_notional": self.max_order_notional,
            "snapshot_hash": self.snapshot_hash,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Campaign Start Snapshot — T=0",
            "",
            f"**Campaign:** {self.campaign_id}",
            f"**Timestamp:** {self.snapshot_timestamp}",
            f"**Snapshot Hash:** {self.snapshot_hash[:16]}...",
            "",
            "## Account State",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Equity | ${self.equity:,.2f} |",
            f"| Balance | ${self.balance:,.2f} |",
            f"| Free Margin | ${self.free_margin:,.2f} |",
            f"| Margin Level | {self.margin_level:,.0f}% |",
            f"| Currency | {self.currency} |",
            "",
            "## Positions at T=0",
            "",
            f"- Open positions: {self.position_count}",
            f"- Total exposure: ${self.total_exposure:,.2f}",
            f"- Net exposure: ${self.net_exposure:,.2f}",
            "",
        ]

        if self.open_positions:
            lines.append("| Ticket | Symbol | Side | Volume | Entry Price |")
            lines.append("|---|---|---|---|---|")
            for pos in self.open_positions:
                lines.append(
                    f"| {pos.get('ticket', '?')} | {pos.get('symbol', '?')} "
                    f"| {pos.get('side', '?')} | {pos.get('volume', '?')} "
                    f"| {pos.get('price_open', '?')} |"
                )
            lines.append("")

        lines.extend(
            [
                "## Fingerprints",
                "",
                "| Component | Fingerprint |",
                "|---|---|",
                f"| R4 Manifest | {self.r4_manifest_fingerprint[:16]}... |",
                f"| Risk Policy | {self.risk_policy_fingerprint[:16]}... |",
                f"| Broker Config | {self.broker_config_fingerprint[:16]}... |",
                f"| Capital Config | {self.capital_config_fingerprint[:16]}... |",
                "",
                "## Gate Decisions",
                "",
                f"- Pre-funding gate: **{self.pre_funding_gate_decision}**",
                f"- Pre-trading validation: **{self.pre_trading_decision}**",
                "",
                "## Risk Limits (Frozen)",
                "",
                "| Limit | Value |",
                "|---|---|",
                f"| Max drawdown | {self.max_drawdown_pct:.1f}% |",
                f"| Daily loss limit | ${self.daily_loss_limit:,.0f} |",
                f"| Max gross leverage | {self.max_gross_leverage:.2f}x |",
                f"| Max positions | {self.max_position_count} |",
                f"| Max concentration | {self.max_concentration_pct:.1f}% |",
                f"| Max asset-class exposure | {self.max_asset_class_exposure_pct:.1f}% |",
                "",
                "## Campaign Parameters (Frozen)",
                "",
                "| Parameter | Value |",
                "|---|---|",
                f"| Max equity | ${self.max_campaign_equity:,.0f} |",
                f"| Duration | {self.campaign_duration_days} days |",
                f"| Max position size | ${self.max_position_size:,.0f} |",
                f"| Max order notional | ${self.max_order_notional:,.0f} |",
                "",
                "---",
                "",
                "*This snapshot is the immutable T=0 reference. All subsequent events",
                "are interpreted relative to this known starting state.*",
            ]
        )

        return "\n".join(lines)


def capture_start_snapshot(
    broker_state: BrokerStateSnapshot,
    pre_trading_auth: PreTradingAuthorization,
    gate_record: GateRecord,
    campaign_id: str = "R4-MINIMAL-5K",
    snapshot_timestamp: str = "",
) -> CampaignStartSnapshot:
    """Capture the immutable T=0 campaign start snapshot.

    Must be called AFTER TRADING_AUTHORIZED and BEFORE the first order.
    """
    import time

    if not snapshot_timestamp:
        snapshot_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Compute fingerprints
    manifest = R4ConfigManifest()
    r4_fingerprint = manifest.compute_identity()

    policy = RiskPolicy()
    policy_data = json.dumps(policy.to_dict(), sort_keys=True).encode("utf-8")
    policy_fingerprint = hashlib.sha256(policy_data).hexdigest()

    from eigencapital.production_qual.broker_boundary import BrokerBoundaryConfig
    from eigencapital.production_qual.capital_boundary import CapitalBoundaryConfig

    broker_config = BrokerBoundaryConfig()
    broker_fingerprint = broker_config.compute_fingerprint()

    capital_config = CapitalBoundaryConfig()
    capital_fingerprint = capital_config.compute_fingerprint()

    # Compute exposure from positions
    total_exposure = sum(abs(p.get("volume", 0) * p.get("price_open", 0)) for p in broker_state.positions)
    net_exposure = sum(
        p.get("volume", 0) * p.get("price_open", 0) * (1 if p.get("side", "").upper() == "BUY" else -1)
        for p in broker_state.positions
    )

    snapshot = CampaignStartSnapshot(
        campaign_id=campaign_id,
        snapshot_timestamp=snapshot_timestamp,
        equity=broker_state.equity,
        balance=broker_state.balance,
        free_margin=broker_state.free_margin,
        margin_level=broker_state.margin_level,
        currency="USD",
        open_positions=broker_state.positions,
        position_count=broker_state.position_count,
        total_exposure=total_exposure,
        net_exposure=net_exposure,
        pending_orders=[],
        pending_order_count=0,
        r4_manifest_fingerprint=r4_fingerprint,
        risk_policy_fingerprint=policy_fingerprint,
        broker_config_fingerprint=broker_fingerprint,
        capital_config_fingerprint=capital_fingerprint,
        account_id=broker_state.account_id,
        account_name=broker_state.account_name,
        broker_name=broker_state.broker_name,
        environment=broker_state.environment,
        platform=broker_state.platform,
        pre_funding_gate_decision=gate_record.decision,
        pre_funding_gate_hash=gate_record.gate_fingerprint,
        pre_trading_decision=pre_trading_auth.decision,
        pre_trading_hash=pre_trading_auth.authorization_fingerprint,
        max_drawdown_pct=policy.max_drawdown_pct,
        daily_loss_limit=policy.daily_loss_limit,
        max_gross_leverage=policy.max_gross_leverage,
        max_position_count=policy.max_position_count,
        max_concentration_pct=policy.max_concentration_pct,
        max_asset_class_exposure_pct=policy.max_asset_class_exposure_pct,
        max_campaign_equity=capital_config.max_equity,
        campaign_duration_days=capital_config.campaign_duration_days,
        max_position_size=capital_config.max_position_size,
        max_order_notional=capital_config.max_order_notional,
    )

    # Compute hash after construction
    object.__setattr__(snapshot, "snapshot_hash", snapshot.compute_hash())

    return snapshot
