"""Pre-Trading Validation Tests — 5-step broker-connected gate.

Covers:
- All 5 validation steps (fund, broker, reconcile, fingerprint, authorize)
- Happy path: clean start, all checks pass
- Negative paths: every failure mode blocks trading
- Position classification: R4, pre-existing, manual, unclassified
- Fingerprint validation: drift detection
- Integration with pre-funding gate record
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from eigencapital.production_qual.broker_boundary import (
    BrokerBoundaryConfig,
)
from eigencapital.production_qual.campaign_boundary import (
    CampaignBoundary,
)
from eigencapital.production_qual.pre_trading import (
    BrokerStateSnapshot,
    PreTradingCheck,
    PreTradingDecision,
    PreTradingValidator,
)
from eigencapital.production_qual.prefunding_gate import (
    GateRecord,
)

# ── Fixtures ──────────────────────────────────────────────────────


def _make_broker_state(
    **overrides: Any,
) -> BrokerStateSnapshot:
    """Create a valid broker state snapshot with sensible defaults."""
    defaults = dict(
        account_id="436921728",
        account_name="EigenCapital-R4",
        environment="demo",
        broker_name="exness",
        platform="mt5",
        equity=5000.0,
        free_margin=4500.0,
        balance=5000.0,
        margin_level=1000.0,
        positions=[],
        position_count=0,
        available_symbols=list(BrokerBoundaryConfig().expected_symbols.keys()),
        symbol_specs={},
        current_spread=0.0005,
        current_slippage=0.0002,
        snapshot_timestamp="2026-08-25T12:00:00Z",
    )
    defaults.update(overrides)
    return BrokerStateSnapshot(**defaults)


def _make_gate_record(
    decision: str = "AUTHORIZED",
) -> GateRecord:
    """Create a gate record for testing."""
    record = GateRecord(
        decision=decision,
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


# ── Step 1: Fund Capital ──────────────────────────────────────────


class TestFundCapital:
    """Step 1: Verify account equity matches authorized boundary."""

    def test_equity_within_boundary(self) -> None:
        """$5K equity passes."""
        validator = PreTradingValidator()
        state = _make_broker_state(equity=5000.0, free_margin=4500.0)
        checks = validator.validate_capital(state)
        assert len(checks) == 3
        assert all(c.passed for c in checks)

    def test_equity_below_boundary(self) -> None:
        """$4K equity still passes (below max)."""
        validator = PreTradingValidator()
        state = _make_broker_state(equity=4000.0, free_margin=3500.0)
        checks = validator.validate_capital(state)
        assert all(c.passed for c in checks)

    def test_equity_exceeds_boundary(self) -> None:
        """$6K equity blocks (exceeds $5K max)."""
        validator = PreTradingValidator()
        state = _make_broker_state(equity=6000.0, free_margin=5500.0)
        checks = validator.validate_capital(state)
        assert not checks[0].passed
        assert checks[0].check_id == "PT-FUND-01"

    def test_zero_equity_blocks(self) -> None:
        """$0 equity: within max but not funded."""
        validator = PreTradingValidator()
        state = _make_broker_state(equity=0.0, free_margin=0.0)
        checks = validator.validate_capital(state)
        assert checks[0].passed  # 0 <= 5000
        assert not checks[1].passed  # not positive

    def test_negative_equity_blocks(self) -> None:
        """Negative equity: within max but not funded."""
        validator = PreTradingValidator()
        state = _make_broker_state(equity=-100.0, free_margin=-100.0)
        checks = validator.validate_capital(state)
        assert checks[0].passed  # -100 <= 5000
        assert not checks[1].passed  # not positive

    def test_no_free_margin_blocks(self) -> None:
        """Zero free margin blocks (can't trade)."""
        validator = PreTradingValidator()
        state = _make_broker_state(equity=5000.0, free_margin=0.0)
        checks = validator.validate_capital(state)
        assert checks[0].passed  # equity OK
        assert checks[1].passed  # positive equity
        assert not checks[2].passed  # no free margin


# ── Step 2: Connect Broker ────────────────────────────────────────


class TestBrokerConnection:
    """Step 2: Revalidate broker boundary against actual broker state."""

    def test_correct_broker_state(self) -> None:
        """Correct account, environment, symbols → all pass."""
        broker_config = BrokerBoundaryConfig(
            expected_account_id="436921728",
            expected_environment="demo",
        )
        validator = PreTradingValidator(broker_config=broker_config)
        state = _make_broker_state()
        checks = validator.validate_broker_connection(state)
        assert len(checks) == 6
        assert all(c.passed for c in checks)

    def test_wrong_account_blocks(self) -> None:
        """Wrong account ID → BLOCKED."""
        broker_config = BrokerBoundaryConfig(
            expected_account_id="436921728",
            expected_environment="demo",
        )
        validator = PreTradingValidator(broker_config=broker_config)
        state = _make_broker_state(account_id="99999999")
        checks = validator.validate_broker_connection(state)
        assert not checks[0].passed
        assert checks[0].check_id == "PT-BROKER-01"

    def test_wrong_environment_blocks(self) -> None:
        """Live instead of demo → BLOCKED."""
        broker_config = BrokerBoundaryConfig(
            expected_account_id="436921728",
            expected_environment="demo",
        )
        validator = PreTradingValidator(broker_config=broker_config)
        state = _make_broker_state(environment="live")
        checks = validator.validate_broker_connection(state)
        assert not checks[1].passed
        assert checks[1].check_id == "PT-BROKER-02"

    def test_missing_symbols_blocks(self) -> None:
        """Missing required symbols → BLOCKED."""
        validator = PreTradingValidator()
        state = _make_broker_state(
            available_symbols=["EURUSDm", "GBPUSDm"]  # only 2 of 15
        )
        checks = validator.validate_broker_connection(state)
        assert not checks[2].passed
        assert checks[2].check_id == "PT-BROKER-03"

    def test_excessive_spread_blocks(self) -> None:
        """Spread exceeds max → BLOCKED."""
        validator = PreTradingValidator()
        state = _make_broker_state(
            symbol_specs={"EURUSD": {"spread": 50}},  # 50 points > 15 point forex limit
        )
        checks = validator.validate_broker_connection(state)
        assert not checks[4].passed
        assert checks[4].check_id == "PT-BROKER-05"

    def test_wrong_broker_blocks(self) -> None:
        """Wrong broker name → BLOCKED (confusion check)."""
        broker_config = BrokerBoundaryConfig(
            expected_account_id="436921728",
            expected_environment="demo",
        )
        validator = PreTradingValidator(broker_config=broker_config)
        state = _make_broker_state(broker_name="oanda")
        checks = validator.validate_broker_connection(state)
        assert not checks[5].passed
        assert checks[5].check_id == "PT-BROKER-06"

    def test_demo_live_confusion_blocks(self) -> None:
        """Live account on demo config → BLOCKED."""
        broker_config = BrokerBoundaryConfig(
            expected_account_id="436921728",
            expected_environment="demo",
        )
        validator = PreTradingValidator(broker_config=broker_config)
        state = _make_broker_state(
            account_id="99999999",
            environment="live",
            broker_name="exness",
        )
        checks = validator.validate_broker_connection(state)
        assert not checks[5].passed


# ── Step 3: Reconcile ─────────────────────────────────────────────


class TestReconcile:
    """Step 3: Classify all positions before first R4 order."""

    def test_clean_start_passes(self) -> None:
        """No positions → clean start, all pass."""
        validator = PreTradingValidator()
        state = _make_broker_state(positions=[], position_count=0)
        checks = validator.reconcile_positions(state)
        assert len(checks) == 4
        assert all(c.passed for c in checks)

    def test_unclassified_position_blocks(self) -> None:
        """Position with unknown ticket → BLOCKED."""
        validator = PreTradingValidator()
        state = _make_broker_state(
            positions=[
                {
                    "ticket": 99999,
                    "symbol": "EURUSDm",
                    "volume": 0.1,
                    "price_open": 1.1000,
                    "time": "2026-08-25T12:00:00",
                }
            ],
            position_count=1,
        )
        checks = validator.reconcile_positions(state)
        assert not checks[0].passed  # unclassified
        assert checks[0].check_id == "PT-RECON-01"

    def test_manual_trade_blocks(self) -> None:
        """Manual trade detected → BLOCKED."""
        boundary = CampaignBoundary(
            campaign_id="test",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-25T00:00:00",
        )
        validator = PreTradingValidator()
        state = _make_broker_state(
            positions=[
                {
                    "ticket": 11111,
                    "symbol": "EURUSDm",
                    "volume": 0.1,
                    "price_open": 1.1000,
                    "time": "2026-08-25T12:00:00",  # after start
                }
            ],
            position_count=1,
        )
        checks = validator.reconcile_positions(state, boundary)
        assert not checks[1].passed  # manual trade
        assert checks[1].check_id == "PT-RECON-02"

    def test_r4_position_classified(self) -> None:
        """R4-originated position → classified correctly."""
        boundary = CampaignBoundary(
            campaign_id="test",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-25T00:00:00",
        )
        from eigencapital.production_qual.campaign_boundary import TradeRecord

        trade = TradeRecord(
            trade_id="T001",
            decision_id="D001",
            evidence_id="E001",
            instrument_id="EURUSDm",
            side="BUY",
            volume=0.1,
            entry_price=1.1000,
            entry_timestamp="2026-08-25T10:00:00",
            broker_ticket=22222,
        )
        boundary.record_r4_trade(trade)

        validator = PreTradingValidator()
        state = _make_broker_state(
            positions=[
                {
                    "ticket": 22222,
                    "symbol": "EURUSDm",
                    "volume": 0.1,
                    "price_open": 1.1000,
                    "time": "2026-08-25T10:00:00",
                }
            ],
            position_count=1,
        )
        checks = validator.reconcile_positions(state, boundary)
        assert all(c.passed for c in checks)
        assert validator._r4_positions == 1

    def test_pre_existing_classified(self) -> None:
        """Pre-existing position → classified correctly."""
        boundary = CampaignBoundary(
            campaign_id="test",
            strategy_fingerprint="abc",
            start_timestamp="2026-08-25T12:00:00",
        )
        validator = PreTradingValidator()
        state = _make_broker_state(
            positions=[
                {
                    "ticket": 33333,
                    "symbol": "GBPUSDm",
                    "volume": 0.2,
                    "price_open": 1.2500,
                    "time": "2026-08-25T10:00:00",  # before start
                }
            ],
            position_count=1,
        )
        checks = validator.reconcile_positions(state, boundary)
        # Pre-existing is OK (documented), but check index depends on order
        pre_existing_check = [c for c in checks if c.check_id == "PT-RECON-04"][0]
        assert pre_existing_check.passed
        assert validator._pre_existing_positions == 1

    def test_position_count_exceeds_limit(self) -> None:
        """Too many positions → BLOCKED."""
        validator = PreTradingValidator()
        positions = [
            {"ticket": i, "symbol": "EURUSDm", "volume": 0.1, "price_open": 1.1000, "time": "2026-08-25T12:00:00"}
            for i in range(10)  # > max 8
        ]
        state = _make_broker_state(positions=positions, position_count=10)
        checks = validator.reconcile_positions(state)
        assert not checks[2].passed
        assert checks[2].check_id == "PT-RECON-03"


# ── Step 4: Validate Fingerprint ──────────────────────────────────


class TestValidateFingerprint:
    """Step 4: Prove connected configuration == frozen R4 manifest."""

    def test_fingerprint_unchanged(self) -> None:
        """Fingerprint matches frozen → PASS."""
        validator = PreTradingValidator()
        state = _make_broker_state()
        checks = validator.validate_fingerprint(state)
        assert len(checks) == 3
        assert all(c.passed for c in checks)

    def test_fingerprint_drift_blocks(self) -> None:
        """Fingerprint changed → BLOCKED."""
        validator = PreTradingValidator()
        # Tamper with the manifest
        object.__setattr__(validator._frozen_manifest, "strategy_version", "R5.0")
        state = _make_broker_state()
        checks = validator.validate_fingerprint(state)
        assert not checks[0].passed  # fingerprint mismatch

    def test_version_drift_blocks(self) -> None:
        """Strategy version changed → BLOCKED."""
        validator = PreTradingValidator()
        object.__setattr__(validator._frozen_manifest, "strategy_version", "R4.1")
        state = _make_broker_state()
        checks = validator.validate_fingerprint(state)
        assert not checks[1].passed  # version mismatch

    def test_terminal_id_mismatch_blocks(self) -> None:
        """Terminal ID doesn't match account → BLOCKED."""
        validator = PreTradingValidator()
        state = _make_broker_state(account_id="99999999")
        checks = validator.validate_fingerprint(state)
        assert not checks[2].passed


# ── Step 5: Authorize ─────────────────────────────────────────────


class TestAuthorize:
    """Step 5: Final authorization gate."""

    def test_gate_authorized_passes(self) -> None:
        """Pre-funding gate AUTHORIZED → PASS."""
        validator = PreTradingValidator()
        gate_record = _make_gate_record(decision="AUTHORIZED")
        checks = validator.authorize_trading(gate_record)
        assert len(checks) == 4
        assert checks[0].passed

    def test_gate_blocked_fails(self) -> None:
        """Pre-funding gate BLOCKED → FAIL."""
        validator = PreTradingValidator()
        gate_record = _make_gate_record(decision="BLOCKED")
        checks = validator.authorize_trading(gate_record)
        assert not checks[0].passed

    def test_no_gate_record_fails(self) -> None:
        """No gate record → FAIL."""
        validator = PreTradingValidator()
        checks = validator.authorize_trading(None)
        assert not checks[0].passed

    def test_critical_failure_blocks(self) -> None:
        """Critical failure in previous step → BLOCKED."""
        validator = PreTradingValidator()
        # Simulate a critical failure
        validator._checks.append(
            PreTradingCheck(
                step="test",
                check_id="TEST-CRIT",
                passed=False,
                description="Test critical failure",
                severity="CRITICAL",
            )
        )
        gate_record = _make_gate_record()
        checks = validator.authorize_trading(gate_record)
        assert not checks[1].passed  # critical failures exist

    def test_unclassified_positions_blocks(self) -> None:
        """Unclassified positions → BLOCKED."""
        validator = PreTradingValidator()
        validator._unclassified_positions = 1
        gate_record = _make_gate_record()
        checks = validator.authorize_trading(gate_record)
        assert not checks[2].passed

    def test_manual_trades_blocks(self) -> None:
        """Manual trades → BLOCKED."""
        validator = PreTradingValidator()
        validator._manual_positions = 1
        gate_record = _make_gate_record()
        checks = validator.authorize_trading(gate_record)
        assert not checks[3].passed


# ── Full Sequence ─────────────────────────────────────────────────


class TestFullValidation:
    """Complete 5-step pre-trading validation sequence."""

    def test_clean_start_all_pass(self) -> None:
        """Clean start, correct broker, gate authorized → TRADING_AUTHORIZED."""
        validator = PreTradingValidator()
        state = _make_broker_state()
        gate_record = _make_gate_record(decision="AUTHORIZED")

        auth = validator.run_full_validation(state, None, gate_record)

        assert auth.decision == PreTradingDecision.TRADING_AUTHORIZED.value
        assert auth.total_checks == 20
        assert auth.passed_checks == 20
        assert auth.critical_failures == []

    def test_wrong_account_blocks(self) -> None:
        """Wrong broker account → TRADING_BLOCKED."""
        broker_config = BrokerBoundaryConfig(
            expected_account_id="436921728",
            expected_environment="demo",
        )
        validator = PreTradingValidator(broker_config=broker_config)
        state = _make_broker_state(account_id="99999999")
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)

        assert auth.decision == PreTradingDecision.TRADING_BLOCKED.value
        assert len(auth.critical_failures) > 0

    def test_demo_live_confusion_blocks(self) -> None:
        """Live account on demo config → TRADING_BLOCKED."""
        broker_config = BrokerBoundaryConfig(
            expected_account_id="436921728",
            expected_environment="demo",
        )
        validator = PreTradingValidator(broker_config=broker_config)
        state = _make_broker_state(environment="live")
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)

        assert auth.decision == PreTradingDecision.TRADING_BLOCKED.value

    def test_excess_equity_blocks(self) -> None:
        """Equity exceeds $5K → TRADING_BLOCKED."""
        validator = PreTradingValidator()
        state = _make_broker_state(equity=10000.0)
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)

        assert auth.decision == PreTradingDecision.TRADING_BLOCKED.value

    def test_unclassified_position_blocks(self) -> None:
        """Unclassified position → TRADING_BLOCKED."""
        validator = PreTradingValidator()
        state = _make_broker_state(
            positions=[
                {
                    "ticket": 99999,
                    "symbol": "EURUSDm",
                    "volume": 0.1,
                    "price_open": 1.1000,
                    "time": "2026-08-25T12:00:00",
                }
            ],
            position_count=1,
        )
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)

        assert auth.decision == PreTradingDecision.TRADING_BLOCKED.value
        assert auth.unclassified_positions == 1

    def test_fingerprint_drift_blocks(self) -> None:
        """Fingerprint drift → TRADING_BLOCKED."""
        validator = PreTradingValidator()
        object.__setattr__(validator._frozen_manifest, "strategy_version", "R5.0")
        state = _make_broker_state()
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)

        assert auth.decision == PreTradingDecision.TRADING_BLOCKED.value

    def test_gate_blocked_blocks(self) -> None:
        """Pre-funding gate BLOCKED → TRADING_BLOCKED."""
        validator = PreTradingValidator()
        state = _make_broker_state()
        gate_record = _make_gate_record(decision="BLOCKED")

        auth = validator.run_full_validation(state, None, gate_record)

        assert auth.decision == PreTradingDecision.TRADING_BLOCKED.value

    def test_no_gate_record_blocks(self) -> None:
        """No gate record → TRADING_BLOCKED."""
        validator = PreTradingValidator()
        state = _make_broker_state()

        auth = validator.run_full_validation(state, None, None)

        assert auth.decision == PreTradingDecision.TRADING_BLOCKED.value

    def test_authorization_record_computed_hash(self) -> None:
        """Authorization record has valid fingerprint."""
        validator = PreTradingValidator()
        state = _make_broker_state()
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)

        assert auth.authorization_fingerprint
        assert len(auth.authorization_fingerprint) == 64  # SHA-256

    def test_authorization_record_immutable(self) -> None:
        """Authorization record is immutable (frozen dataclass)."""
        validator = PreTradingValidator()
        state = _make_broker_state()
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)

        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            auth.decision = "TAMPERED"  # type: ignore[misc]

    def test_position_classification_recorded(self) -> None:
        """Position counts are recorded in authorization."""
        validator = PreTradingValidator()
        state = _make_broker_state(
            positions=[
                {
                    "ticket": 11111,
                    "symbol": "EURUSDm",
                    "volume": 0.1,
                    "price_open": 1.1000,
                    "time": "2026-08-25T12:00:00",
                }
            ],
            position_count=1,
        )
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)

        assert auth.unclassified_positions == 1
        assert auth.r4_positions == 0
        assert auth.manual_positions == 0

    def test_authorization_to_dict(self) -> None:
        """Authorization record serializes to dict."""
        validator = PreTradingValidator()
        state = _make_broker_state()
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)
        d = auth.to_dict()

        assert d["decision"] == "TRADING_AUTHORIZED"
        assert d["campaign_id"] == "R4-MINIMAL-5K"
        assert d["total_checks"] == 20
        assert d["passed_checks"] == 20
        assert "checks" in d

    def test_authorization_to_markdown(self) -> None:
        """Authorization record renders to markdown."""
        validator = PreTradingValidator()
        state = _make_broker_state()
        gate_record = _make_gate_record()

        auth = validator.run_full_validation(state, None, gate_record)
        md = auth.to_markdown()

        assert "TRADING_AUTHORIZED" in md
        assert "Pre-Trading Validation" in md
        assert "R4 Campaign" in md


# ── Negative-Path Matrix ──────────────────────────────────────────


class TestNegativePathMatrix:
    """Every important failure mode has a predetermined safe outcome."""

    @pytest.mark.parametrize(
        "failure,expected",
        [
            ("wrong_account", "TRADING_BLOCKED"),
            ("wrong_environment", "TRADING_BLOCKED"),
            ("wrong_broker", "TRADING_BLOCKED"),
            ("excess_equity", "TRADING_BLOCKED"),
            ("zero_equity", "TRADING_BLOCKED"),
            ("missing_symbols", "TRADING_BLOCKED"),
            ("excessive_spread", "TRADING_BLOCKED"),
            ("unclassified_position", "TRADING_BLOCKED"),
            ("manual_trade", "TRADING_BLOCKED"),
            ("fingerprint_drift", "TRADING_BLOCKED"),
            ("version_drift", "TRADING_BLOCKED"),
            ("gate_blocked", "TRADING_BLOCKED"),
            ("no_gate_record", "TRADING_BLOCKED"),
            ("position_limit_exceeded", "TRADING_BLOCKED"),
        ],
    )
    def test_failure_blocks_trading(self, failure: str, expected: str) -> None:
        """Each failure mode → TRADING_BLOCKED."""
        validator = PreTradingValidator()
        gate_record = _make_gate_record()

        # Configure the failure
        if failure == "wrong_account":
            state = _make_broker_state(account_id="99999999")
        elif failure == "wrong_environment":
            state = _make_broker_state(environment="live")  # expects demo, gets live
        elif failure == "wrong_broker":
            state = _make_broker_state(broker_name="oanda")
        elif failure == "excess_equity":
            state = _make_broker_state(equity=10000.0)
        elif failure == "zero_equity":
            state = _make_broker_state(equity=0.0, free_margin=0.0)
        elif failure == "missing_symbols":
            state = _make_broker_state(available_symbols=["EURUSDm"])
        elif failure == "excessive_spread":
            state = _make_broker_state(symbol_specs={"EURUSD": {"spread": 50}})
        elif failure == "unclassified_position":
            state = _make_broker_state(
                positions=[
                    {
                        "ticket": 99999,
                        "symbol": "EURUSDm",
                        "volume": 0.1,
                        "price_open": 1.1,
                        "time": "2026-08-25T12:00:00",
                    }
                ],
                position_count=1,
            )
        elif failure == "manual_trade":
            state = _make_broker_state(
                positions=[
                    {
                        "ticket": 11111,
                        "symbol": "EURUSDm",
                        "volume": 0.1,
                        "price_open": 1.1,
                        "time": "2026-08-25T12:00:00",
                    }
                ],
                position_count=1,
            )
            boundary = CampaignBoundary(
                campaign_id="test",
                strategy_fingerprint="abc",
                start_timestamp="2026-08-25T00:00:00",
            )
            auth = validator.run_full_validation(state, boundary, gate_record)
            assert auth.decision == expected
            return
        elif failure == "fingerprint_drift":
            state = _make_broker_state()
            object.__setattr__(validator._frozen_manifest, "strategy_version", "R5.0")
        elif failure == "version_drift":
            state = _make_broker_state()
            object.__setattr__(validator._frozen_manifest, "strategy_version", "R4.1")
        elif failure == "gate_blocked":
            state = _make_broker_state()
            gate_record = _make_gate_record(decision="BLOCKED")
        elif failure == "no_gate_record":
            state = _make_broker_state()
            gate_record = None  # type: ignore[assignment]
        elif failure == "position_limit_exceeded":
            positions = [
                {"ticket": i, "symbol": "EURUSDm", "volume": 0.1, "price_open": 1.1, "time": "2026-08-25T12:00:00"}
                for i in range(10)
            ]
            state = _make_broker_state(positions=positions, position_count=10)
        else:
            state = _make_broker_state()

        auth = validator.run_full_validation(state, None, gate_record)
        assert auth.decision == expected, f"Failure '{failure}' should produce {expected}"
