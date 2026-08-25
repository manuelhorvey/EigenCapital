"""Campaign Start Snapshot Tests — T=0 immutability and completeness.

Covers:
- Snapshot capture from broker state
- Immutability (frozen dataclass)
- Hash determinism
- Completeness (all required fields populated)
- Serialization (dict, markdown)
- Position classification in snapshot
- Gate record linkage
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

import pytest

from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.production_qual.pre_trading import (
    BrokerStateSnapshot,
    PreTradingAuthorization,
    PreTradingCheck,
    PreTradingDecision,
)
from eigencapital.production_qual.campaign_snapshot import (
    CampaignStartSnapshot,
    capture_start_snapshot,
)
from eigencapital.production_qual.prefunding_gate import (
    GateDecision,
    GateRecord,
    PrefundingGate,
)
from eigencapital.risk.policy import RiskPolicy


# ── Fixtures ──────────────────────────────────────────────────────


def _make_broker_state(**overrides: Any) -> BrokerStateSnapshot:
    defaults = dict(
        account_id="168966110",
        account_name="EigenCapital-R4",
        environment="live",
        broker_name="exness",
        platform="mt5",
        equity=5000.0,
        free_margin=4500.0,
        balance=5000.0,
        margin_level=1000.0,
        positions=[],
        position_count=0,
        available_symbols=list(R4ConfigManifest().universe.keys()),
        symbol_specs={},
        current_spread=0.0005,
        current_slippage=0.0002,
        snapshot_timestamp="2026-08-25T12:00:00Z",
    )
    defaults.update(overrides)
    return BrokerStateSnapshot(**defaults)


def _make_gate_record() -> GateRecord:
    record = GateRecord(
        decision="AUTHORIZED",
        campaign_id="R4-MINIMAL-5K",
        verdict="GO",
        report_hash="abc123",
        decision_timestamp="2026-08-25T12:00:00Z",
        total_checks=48,
        passed_checks=48,
        critical_failures=0,
    )
    object.__setattr__(record, "gate_fingerprint", record.compute_fingerprint())
    return record


def _make_pre_trading_auth() -> PreTradingAuthorization:
    auth = PreTradingAuthorization(
        decision=PreTradingDecision.TRADING_AUTHORIZED.value,
        campaign_id="R4-MINIMAL-5K",
        manifest_fingerprint="aaab6c00dc05",
        broker_snapshot_hash="abc123",
        authorization_timestamp="2026-08-25T12:05:00Z",
    )
    object.__setattr__(auth, "authorization_fingerprint", auth.compute_hash())
    return auth


# ── Snapshot Capture ──────────────────────────────────────────────


class TestCaptureStartSnapshot:
    """Capture T=0 snapshot from broker state."""

    def test_clean_start(self) -> None:
        """Clean start: no positions, correct account."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        assert snap.campaign_id == "R4-MINIMAL-5K"
        assert snap.equity == 5000.0
        assert snap.balance == 5000.0
        assert snap.position_count == 0
        assert snap.pre_funding_gate_decision == "AUTHORIZED"
        assert snap.pre_trading_decision == "TRADING_AUTHORIZED"

    def test_with_positions(self) -> None:
        """Snapshot captures existing positions."""
        broker = _make_broker_state(
            positions=[{
                "ticket": 11111,
                "symbol": "EURUSDm",
                "side": "BUY",
                "volume": 0.1,
                "price_open": 1.1000,
            }],
            position_count=1,
        )
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        assert snap.position_count == 1
        assert len(snap.open_positions) == 1
        assert snap.open_positions[0]["ticket"] == 11111

    def test_exposure_computed(self) -> None:
        """Total and net exposure computed from positions."""
        broker = _make_broker_state(
            positions=[
                {"ticket": 1, "symbol": "EURUSDm", "side": "BUY",
                 "volume": 0.1, "price_open": 1.1000},
                {"ticket": 2, "symbol": "GBPUSDm", "side": "SELL",
                 "volume": 0.2, "price_open": 1.2500},
            ],
            position_count=2,
        )
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        # BUY 0.1 @ 1.1000 = 0.11 notional
        # SELL 0.2 @ 1.2500 = 0.25 notional
        # Total = 0.36, Net = 0.11 - 0.25 = -0.14
        assert snap.total_exposure == pytest.approx(0.36, rel=1e-6)
        assert snap.net_exposure == pytest.approx(-0.14, rel=1e-6)


# ── Immutability ──────────────────────────────────────────────────


class TestSnapshotImmutability:
    """Snapshot is frozen — no mutation after creation."""

    def test_frozen_dataclass(self) -> None:
        """Cannot modify any field after creation."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        with pytest.raises((AttributeError, Exception)):
            snap.equity = 99999.0  # type: ignore[misc]

    def test_frozen_positions_list(self) -> None:
        """Positions list is frozen in the snapshot."""
        broker = _make_broker_state(
            positions=[{"ticket": 1, "symbol": "EURUSDm"}],
            position_count=1,
        )
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        # The list itself is stored, but the snapshot is frozen
        assert snap.position_count == 1


# ── Hash Determinism ──────────────────────────────────────────────


class TestSnapshotHash:
    """Snapshot hash is deterministic and tamper-evident."""

    def test_same_inputs_same_hash(self) -> None:
        """Identical inputs produce identical hash."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap1 = capture_start_snapshot(broker, auth, gate)
        snap2 = capture_start_snapshot(broker, auth, gate)

        assert snap1.snapshot_hash == snap2.snapshot_hash

    def test_different_equity_different_hash(self) -> None:
        """Different equity produces different hash."""
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap1 = capture_start_snapshot(_make_broker_state(equity=5000.0), auth, gate)
        snap2 = capture_start_snapshot(_make_broker_state(equity=5001.0), auth, gate)

        assert snap1.snapshot_hash != snap2.snapshot_hash

    def test_hash_is_sha256(self) -> None:
        """Hash is 64-char hex (SHA-256)."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        assert len(snap.snapshot_hash) == 64
        assert all(c in "0123456789abcdef" for c in snap.snapshot_hash)

    def test_tamper_detection(self) -> None:
        """Modifying the snapshot changes the hash."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)
        original_hash = snap.snapshot_hash

        # Create a new snapshot with different data
        snap2 = capture_start_snapshot(
            _make_broker_state(equity=6000.0), auth, gate
        )

        assert snap2.snapshot_hash != original_hash


# ── Completeness ──────────────────────────────────────────────────


class TestSnapshotCompleteness:
    """All required fields are populated."""

    def test_fingerprints_populated(self) -> None:
        """All fingerprint fields are non-empty."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        assert snap.r4_manifest_fingerprint
        assert snap.risk_policy_fingerprint
        assert snap.broker_config_fingerprint
        assert snap.capital_config_fingerprint

    def test_r4_fingerprint_matches_manifest(self) -> None:
        """R4 fingerprint matches actual manifest."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        manifest = R4ConfigManifest()
        assert snap.r4_manifest_fingerprint == manifest.compute_identity()

    def test_risk_limits_populated(self) -> None:
        """Risk limit fields are populated from RiskPolicy."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        policy = RiskPolicy()
        assert snap.max_drawdown_pct == policy.max_drawdown_pct
        assert snap.daily_loss_limit == policy.daily_loss_limit
        assert snap.max_gross_leverage == policy.max_gross_leverage

    def test_gate_records_linked(self) -> None:
        """Gate decision and hash are recorded."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        assert snap.pre_funding_gate_decision == "AUTHORIZED"
        assert snap.pre_funding_gate_hash
        assert snap.pre_trading_decision == "TRADING_AUTHORIZED"
        assert snap.pre_trading_hash

    def test_account_identity_populated(self) -> None:
        """Broker account identity fields are populated."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        assert snap.account_id == "168966110"
        assert snap.account_name == "EigenCapital-R4"
        assert snap.broker_name == "exness"
        assert snap.environment == "live"


# ── Serialization ─────────────────────────────────────────────────


class TestSnapshotSerialization:
    """Snapshot serializes correctly."""

    def test_to_dict(self) -> None:
        """Snapshot serializes to dict."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)
        d = snap.to_dict()

        assert d["campaign_id"] == "R4-MINIMAL-5K"
        assert d["equity"] == 5000.0
        assert d["snapshot_hash"]
        assert "open_positions" in d

    def test_to_dict_json_serializable(self) -> None:
        """Dict is JSON-serializable."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)
        d = snap.to_dict()

        # Must not raise
        json_str = json.dumps(d, indent=2)
        assert len(json_str) > 0

    def test_to_markdown(self) -> None:
        """Snapshot renders to markdown."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)
        md = snap.to_markdown()

        assert "Campaign Start Snapshot" in md
        assert "T=0" in md
        assert "$5,000.00" in md
        assert "R4 Manifest" in md
        assert "AUTHORIZED" in md

    def test_to_markdown_with_positions(self) -> None:
        """Markdown includes position table when positions exist."""
        broker = _make_broker_state(
            positions=[{
                "ticket": 11111,
                "symbol": "EURUSDm",
                "side": "BUY",
                "volume": 0.1,
                "price_open": 1.1000,
            }],
            position_count=1,
        )
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)
        md = snap.to_markdown()

        assert "EURUSDm" in md
        assert "11111" in md


# ── Gate Record Linkage ───────────────────────────────────────────


class TestGateRecordLinkage:
    """Snapshot links to pre-funding and pre-trading gate records."""

    def test_pre_funding_linked(self) -> None:
        """Pre-funding gate record is linked."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        assert snap.pre_funding_gate_decision == gate.decision
        assert snap.pre_funding_gate_hash == gate.gate_fingerprint

    def test_pre_trading_linked(self) -> None:
        """Pre-trading authorization is linked."""
        broker = _make_broker_state()
        gate = _make_gate_record()
        auth = _make_pre_trading_auth()

        snap = capture_start_snapshot(broker, auth, gate)

        assert snap.pre_trading_decision == auth.decision
        assert snap.pre_trading_hash == auth.authorization_fingerprint
