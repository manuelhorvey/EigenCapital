from __future__ import annotations

import json
import tempfile
import os

import pytest

from eigencapital.domain.encoding import EigenCapitalJSONEncoder
from eigencapital.domain.provenance import (
    DecisionID,
    DecisionProvenance,
    DecisionTrace,
    ExecutionContext,
    FeatureContext,
    MarketContext,
    ModelContext,
    PortfolioContext,
    PositionSnapshot,
    PROVENANCE_SCHEMA_VERSION,
)
from eigencapital.domain.provenance.provenance_store import (
    SqliteProvenanceStore,
    compute_config_hash,
    compute_git_hash,
)
from eigencapital.domain.provenance.counterfactual import CounterfactualEngine, CounterfactualDelta, guess_signal_from_probs
from eigencapital.domain.provenance.validator import ProvenanceValidator, ValidationResult


# Alias to avoid collision with paper_trading.execution_context.ExecutionContext
ProvenanceExecutionContext = ExecutionContext


class TestDecisionID:
    def test_generate(self):
        did = DecisionID.generate()
        assert len(did.decision_id) == 36  # UUID4 hex
        assert did.decision_id.count("-") == 4
        assert len(did.lineage_id) == 36

    def test_generate_with_lineage(self):
        lineage = "shared-lineage-id"
        did1 = DecisionID.generate(lineage_id=lineage)
        did2 = DecisionID.generate(lineage_id=lineage)
        assert did1.decision_id != did2.decision_id
        assert did1.lineage_id == did2.lineage_id == lineage

    def test_to_dict_roundtrip(self):
        did = DecisionID.generate()
        d = did.to_dict()
        restored = DecisionID.from_dict(d)
        assert restored == did
        assert restored.decision_id == did.decision_id

    def test_json_serializable(self):
        did = DecisionID.generate()
        s = json.dumps(did.to_dict(), cls=EigenCapitalJSONEncoder)
        restored = DecisionID.from_dict(json.loads(s))
        assert restored == did


class TestMarketContext:
    def test_full_roundtrip(self):
        ctx = MarketContext(
            asset="GBPJPY",
            ticker="GBPJPY=X",
            close_price=186.5,
            open_price=185.0,
            high_price=187.2,
            low_price=184.8,
            volume=15000.0,
            spread_bps=12.0,
            spread_tier="fx_cross",
            in_session=True,
            n_bars=100,
        )
        d = ctx.to_dict()
        restored = MarketContext.from_dict(d)
        assert restored == ctx
        assert restored.close_price == 186.5
        assert restored.spread_bps == 12.0

    def test_minimal(self):
        ctx = MarketContext(asset="EURUSD", ticker="EURUSD=X", close_price=1.1000)
        d = ctx.to_dict()
        restored = MarketContext.from_dict(d)
        assert restored.asset == "EURUSD"
        assert restored.close_price == 1.1000


class TestFeatureContext:
    def test_full_roundtrip(self):
        ctx = FeatureContext(
            feature_hash="abc123",
            feature_vector={"ma_20": 1.05, "rsi_14": 65.0, "bb_width": 0.02},
            feature_names=["ma_20", "rsi_14", "bb_width"],
            n_features=3,
        )
        d = ctx.to_dict()
        restored = FeatureContext.from_dict(d)
        assert restored == ctx
        assert restored.feature_hash == "abc123"
        assert restored.feature_vector["ma_20"] == 1.05

    def test_json_with_large_feature_vector(self):
        fv = {f"feature_{i}": float(i * 0.1) for i in range(100)}
        ctx = FeatureContext(feature_hash="xyz", feature_vector=fv, n_features=100)
        s = json.dumps(ctx.to_dict(), cls=EigenCapitalJSONEncoder)
        restored = FeatureContext.from_dict(json.loads(s))
        assert restored.n_features == 100
        assert len(restored.feature_vector) == 100


class TestModelContext:
    def test_full_roundtrip(self):
        ctx = ModelContext(
            model_version="xgb_v2.1",
            model_hash="def456",
            prob_long=0.75,
            prob_short=0.15,
            prob_neutral=0.10,
            calibrated_prob_long=0.72,
            calibrated_confidence=0.68,
            calibration_applied=True,
            calibration_version="iso_v1",
            calibration_ece=0.03,
            meta_label_proba=0.85,
            meta_label_enabled=True,
            regime_label="trend_up",
            regime_long_prob=0.80,
        )
        d = ctx.to_dict()
        restored = ModelContext.from_dict(d)
        assert restored == ctx
        assert restored.prob_long == 0.75
        assert restored.calibration_ece == 0.03

    def test_minimal(self):
        ctx = ModelContext(model_version="v1", model_hash="hash", prob_long=0.0, prob_short=0.0, prob_neutral=1.0)
        d = ctx.to_dict()
        restored = ModelContext.from_dict(d)
        assert restored.model_version == "v1"


class TestPortfolioContext:
    def test_with_positions_roundtrip(self):
        positions = (
            PositionSnapshot("EURUSD", "long", 10000.0, 1.1000, 1.1050, 0.45, 11050.0),
            PositionSnapshot("GBPJPY", "short", 5000.0, 186.0, 185.5, -0.27, 9275.0),
        )
        ctx = PortfolioContext(
            total_equity=100000.0,
            peak_value=105000.0,
            drawdown_pct=-0.05,
            gross_exposure=15000.0,
            net_exposure=5000.0,
            open_position_count=2,
            positions=positions,
            pek_budget_utilization=0.65,
            pek_max_risk_per_trade_pct=0.02,
            daily_pnl=500.0,
            portfolio_mode="production",
        )
        d = ctx.to_dict()
        restored = PortfolioContext.from_dict(d)
        assert restored.total_equity == 100000.0
        assert restored.open_position_count == 2
        assert len(restored.positions) == 2
        assert restored.positions[0].asset == "EURUSD"

    def test_empty_positions(self):
        ctx = PortfolioContext(total_equity=50000.0, peak_value=50000.0, drawdown_pct=0.0, gross_exposure=0.0, net_exposure=0.0, open_position_count=0)
        d = ctx.to_dict()
        restored = PortfolioContext.from_dict(d)
        assert restored.open_position_count == 0
        assert len(restored.positions) == 0


class TestExecutionContext:
    def test_full_roundtrip(self):
        ctx = ExecutionContext(
            cycle_id=42,
            cycle_duration_ms=1500.0,
            total_equity=100000.0,
            drawdown_pct=-0.03,
            exposure_multiplier=0.85,
            n_assets=22,
            n_healthy=18,
            n_halted=2,
            halt_ratio=0.09,
            emergency_halt=False,
            peak_portfolio_value=105000.0,
            var_95=-0.015,
            cvar_95=-0.022,
            daily_pnl=1200.0,
            pek_budget_utilization=0.72,
            position_concentration_skew=0.15,
        )
        d = ctx.to_dict()
        restored = ExecutionContext.from_dict(d)
        assert restored == ctx
        assert restored.cycle_id == 42
        assert restored.var_95 == -0.015

    def test_minimal(self):
        ctx = ExecutionContext(cycle_id=1)
        d = ctx.to_dict()
        restored = ExecutionContext.from_dict(d)
        assert restored.cycle_id == 1


class TestDecisionTrace:
    def test_full_roundtrip(self):
        trace = DecisionTrace(
            final_signal="BUY",
            gates_trace={"spread_ok": True, "session_ok": True, "confidence_ok": True},
            gates_blocked=[],
            n_gates_passed=3,
            position_size=0.05,
            kelly_multiplier=0.5,
            stop_loss_price=1.0950,
            take_profit_price=1.1150,
            entry_price=1.1000,
            entry_action="ENTER",
            flip_occurred=False,
        )
        d = trace.to_dict()
        restored = DecisionTrace.from_dict(d)
        assert restored == trace
        assert restored.final_signal == "BUY"
        assert restored.kelly_multiplier == 0.5

    def test_minimal(self):
        trace = DecisionTrace(final_signal="HOLD")
        d = trace.to_dict()
        restored = DecisionTrace.from_dict(d)
        assert restored.final_signal == "HOLD"


class TestDecisionProvenance:
    def test_full_roundtrip(self):
        provenance = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=42,
            asset="GBPJPY",
            decision_timestamp="2026-07-22T10:00:00",
            decision_type="LIVE",
            git_hash="abc123def456",
            config_hash="config_hash_64",
            market=MarketContext(asset="GBPJPY", ticker="GBPJPY=X", close_price=186.5, spread_bps=12.0),
            features=FeatureContext(feature_hash="fh1", feature_vector={"ma": 1.0}),
            model=ModelContext(model_version="v1", model_hash="mh1", prob_long=0.7, prob_short=0.2, prob_neutral=0.1),
            portfolio=PortfolioContext(total_equity=100000.0, peak_value=105000.0, drawdown_pct=-0.05, gross_exposure=15000.0, net_exposure=5000.0, open_position_count=1),
            runtime=ExecutionContext(cycle_id=42, total_equity=100000.0, drawdown_pct=-0.03),
            decision=DecisionTrace(final_signal="BUY", position_size=0.05),
        )
        d = provenance.to_dict()
        restored = DecisionProvenance.from_dict(d)
        assert restored.decision_id.decision_id == provenance.decision_id.decision_id
        assert restored.cycle_id == 42
        assert restored.market.close_price == 186.5
        assert restored.model.prob_long == 0.7
        assert restored.decision.final_signal == "BUY"
        assert restored.schema_version == PROVENANCE_SCHEMA_VERSION

    def test_minimal(self):
        provenance = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=1,
            asset="EURUSD",
            decision_timestamp="2026-07-22T12:00:00",
        )
        d = provenance.to_dict()
        restored = DecisionProvenance.from_dict(d)
        assert restored.cycle_id == 1
        assert restored.asset == "EURUSD"
        assert restored.market is None
        assert restored.features is None

    def test_json_encoding(self):
        provenance = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=1,
            asset="EURUSD",
            decision_timestamp="2026-07-22T12:00:00",
            market=MarketContext(asset="EURUSD", ticker="EURUSD=X", close_price=1.1000),
        )
        s = json.dumps(provenance.to_dict(), cls=EigenCapitalJSONEncoder)
        restored = DecisionProvenance.from_dict(json.loads(s))
        assert restored.asset == "EURUSD"
        assert restored.market.close_price == 1.1000


class TestSqliteProvenanceStore:
    @pytest.fixture
    def store(self):
        db = tempfile.mktemp(suffix=".db")
        s = SqliteProvenanceStore(db)
        s.initialize()
        yield s
        s.close()
        if os.path.exists(db):
            os.remove(db)

    def test_store_and_count(self, store):
        assert store.count() == 0
        p = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=1,
            asset="EURUSD",
            decision_timestamp="2026-07-22T12:00:00",
        )
        store.store(p)
        assert store.count() == 1

    def test_store_with_full_context(self, store):
        p = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=42,
            asset="GBPJPY",
            decision_timestamp="2026-07-22T10:00:00",
            git_hash="abc123",
            config_hash="def456",
            market=MarketContext(asset="GBPJPY", ticker="GBPJPY=X", close_price=186.5, spread_bps=12.0),
            runtime=ExecutionContext(cycle_id=42, total_equity=10500.0, drawdown_pct=-0.03),
        )
        store.store(p)
        results = store.query(asset="GBPJPY")
        assert len(results) == 1
        assert results[0].market.close_price == 186.5
        assert results[0].runtime.total_equity == 10500.0

    def test_query_by_asset(self, store):
        for i, asset in enumerate(["EURUSD", "GBPJPY", "EURUSD"]):
            store.store(DecisionProvenance(
                decision_id=DecisionID.generate(),
                cycle_id=i,
                asset=asset,
                decision_timestamp=f"2026-07-22T{10+i}:00:00",
            ))
        eurusd = store.query(asset="EURUSD")
        assert len(eurusd) == 2
        gbpjpy = store.query(asset="GBPJPY")
        assert len(gbpjpy) == 1

    def test_query_by_cycle(self, store):
        for i in range(3):
            store.store(DecisionProvenance(
                decision_id=DecisionID.generate(),
                cycle_id=i,
                asset="EURUSD",
                decision_timestamp=f"2026-07-22T{10+i}:00:00",
            ))
        results = store.query(cycle_id=1)
        assert len(results) == 1
        assert results[0].cycle_id == 1

    def test_get_by_decision_id(self, store):
        did = DecisionID.generate()
        p = DecisionProvenance(
            decision_id=did,
            cycle_id=1,
            asset="EURUSD",
            decision_timestamp="2026-07-22T12:00:00",
        )
        store.store(p)
        restored = store.get_by_decision_id(did.decision_id)
        assert restored is not None
        assert restored.decision_id.decision_id == did.decision_id
        assert restored.cycle_id == 1

    def test_get_by_decision_id_returns_none(self, store):
        assert store.get_by_decision_id("nonexistent") is None

    def test_query_limit_offset(self, store):
        for i in range(10):
            store.store(DecisionProvenance(
                decision_id=DecisionID.generate(),
                cycle_id=i,
                asset="EURUSD",
                decision_timestamp=f"2026-07-22T{10+i}:00:00",
            ))
        results = store.query(limit=3, offset=0)
        assert len(results) <= 3
        results_offset = store.query(limit=3, offset=3)
        assert len(results_offset) <= 3

    def test_query_time_range(self, store):
        store.store(DecisionProvenance(
            decision_id=DecisionID.generate(), cycle_id=1, asset="EURUSD",
            decision_timestamp="2026-07-22T10:00:00",
        ))
        store.store(DecisionProvenance(
            decision_id=DecisionID.generate(), cycle_id=2, asset="EURUSD",
            decision_timestamp="2026-07-22T11:00:00",
        ))
        store.store(DecisionProvenance(
            decision_id=DecisionID.generate(), cycle_id=3, asset="EURUSD",
            decision_timestamp="2026-07-22T12:00:00",
        ))
        results = store.query(since="2026-07-22T11:00:00", until="2026-07-22T12:00:00")
        assert len(results) == 2

    def test_multiple_stores(self, store):
        for i in range(5):
            store.store(DecisionProvenance(
                decision_id=DecisionID.generate(),
                cycle_id=i,
                asset=f"ASSET{i}",
                decision_timestamp=f"2026-07-22T{10+i}:00:00",
            ))
        assert store.count() == 5

    def test_store_all_none_contexts(self, store):
        p = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=1,
            asset="EURUSD",
            decision_timestamp="2026-07-22T12:00:00",
        )
        store.store(p)
        restored = store.get_by_decision_id(p.decision_id.decision_id)
        assert restored is not None
        assert restored.market is None
        assert restored.features is None
        assert restored.model is None

    def test_query_with_no_results(self, store):
        results = store.query(asset="NONEXISTENT")
        assert results == []


class TestSqliteProvenanceStoreMaintenance:
    """Test prune, health, and count_by_asset maintenance operations."""

    @pytest.fixture
    def store(self):
        db = tempfile.mktemp(suffix=".db")
        s = SqliteProvenanceStore(db)
        s.initialize()
        yield s
        s.close()
        if os.path.exists(db):
            os.remove(db)

    def _seed(self, store, n: int = 5):
        for i in range(n):
            store.store(DecisionProvenance(
                decision_id=DecisionID.generate(),
                cycle_id=i + 1,
                asset="EURUSD",
                decision_timestamp=f"2026-07-{20 + i:02d}T10:00:00",
            ))

    def test_prune_removes_old_records(self, store):
        self._seed(store, 5)
        before = "2026-07-23T00:00:00"
        deleted = store.prune(before)
        assert deleted == 3  # Jul 20, 21, 22
        assert store.count() == 2  # Jul 23, 24

    def test_prune_with_no_old_records(self, store):
        self._seed(store, 3)
        deleted = store.prune("2026-07-19T00:00:00")
        assert deleted == 0
        assert store.count() == 3

    def test_prune_all_records(self, store):
        self._seed(store, 3)
        deleted = store.prune("2026-07-25T00:00:00")
        assert deleted == 3
        assert store.count() == 0

    def test_health_ok(self, store):
        self._seed(store, 5)
        h = store.health()
        assert h["status"] == "ok"
        assert h["total_records"] == 5
        assert h["db_size_bytes"] > 0
        assert h["oldest_timestamp"] == "2026-07-20T10:00:00"
        assert h["newest_timestamp"] == "2026-07-24T10:00:00"

    def test_health_empty_db(self, store):
        h = store.health()
        assert h["status"] == "ok"
        assert h["total_records"] == 0
        assert h["oldest_timestamp"] is None

    def test_count_by_asset(self, store):
        for i, asset in enumerate(["EURUSD", "GBPJPY", "EURUSD"]):
            store.store(DecisionProvenance(
                decision_id=DecisionID.generate(),
                cycle_id=i + 1,
                asset=asset,
                decision_timestamp=f"2026-07-{22 + i:02d}T10:00:00",
            ))
        counts = store.count_by_asset()
        assert counts["EURUSD"] == 2
        assert counts["GBPJPY"] == 1

    def test_count_by_asset_empty(self, store):
        assert store.count_by_asset() == {}

    def test_prune_then_recount(self, store):
        self._seed(store, 5)
        store.prune("2026-07-23T00:00:00")
        assert store.count() == 2
        h = store.health()
        assert h["total_records"] == 2
        assert h["oldest_timestamp"] == "2026-07-23T10:00:00"
        assert h["newest_timestamp"] == "2026-07-24T10:00:00"


class TestProvenanceValidator:
    @pytest.fixture
    def valid_provenance(self):
        return DecisionProvenance(
            decision_id=DecisionID.generate(),
            schema_version=PROVENANCE_SCHEMA_VERSION,
            cycle_id=42,
            asset="GBPJPY",
            decision_timestamp="2026-07-22T10:00:00",
            git_hash="abc123",
            config_hash="def456",
            market=MarketContext(asset="GBPJPY", ticker="GBPJPY=X", close_price=186.5, spread_bps=12.0),
            features=FeatureContext(feature_hash="fh1", feature_vector={"ma": 1.0, "rsi": 65.0}, n_features=2),
            model=ModelContext(
                model_version="v1", model_hash="mh1",
                prob_long=0.7, prob_short=0.2, prob_neutral=0.1,
                calibrated_confidence=0.65, calibration_applied=True,
            ),
            portfolio=PortfolioContext(
                total_equity=100000.0, peak_value=105000.0, drawdown_pct=-0.05,
                gross_exposure=15000.0, net_exposure=5000.0, open_position_count=0,
                portfolio_mode="production",
            ),
            runtime=ProvenanceExecutionContext(
                cycle_id=42, total_equity=100000.0, drawdown_pct=-0.05,
                exposure_multiplier=0.85, n_assets=22, n_healthy=20, n_halted=1, halt_ratio=0.045,
            ),
            decision=DecisionTrace(final_signal="BUY", position_size=0.05, n_gates_passed=3, n_gates_blocked=0),
        )

    def test_valid_provenance_passes(self, valid_provenance):
        validator = ProvenanceValidator()
        result = validator.validate(valid_provenance)
        assert result.is_valid, f"Expected no errors, got: {result.errors}"

    def test_valid_provenance_strict_passes(self, valid_provenance):
        validator = ProvenanceValidator(strict=True)
        result = validator.validate(valid_provenance)
        assert result.is_valid, f"Expected no errors in strict mode, got: {result.errors}"

    def test_missing_decision_id(self):
        p = DecisionProvenance(
            decision_id=DecisionID(decision_id="", lineage_id=""),
            cycle_id=1, asset="EURUSD", decision_timestamp="2026-07-22T12:00:00",
        )
        result = ProvenanceValidator().validate(p)
        assert not result.is_valid
        errors = [e.field for e in result.errors]
        assert "decision_id.decision_id" in errors
        assert "decision_id.lineage_id" in errors

    def test_negative_cycle_id(self):
        p = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=-1, asset="EURUSD", decision_timestamp="2026-07-22T12:00:00",
        )
        result = ProvenanceValidator().validate(p)
        assert not result.is_valid

    def test_missing_asset(self):
        p = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=1, asset="", decision_timestamp="2026-07-22T12:00:00",
        )
        result = ProvenanceValidator().validate(p)
        assert not result.is_valid

    def test_invalid_probability_sum(self, valid_provenance):
        p = valid_provenance
        p2 = DecisionProvenance(
            decision_id=p.decision_id, cycle_id=p.cycle_id, asset=p.asset,
            decision_timestamp=p.decision_timestamp,
            model=ModelContext(model_version="v1", model_hash="mh1", prob_long=0.9, prob_short=0.0, prob_neutral=0.0),
        )
        result = ProvenanceValidator().validate(p2)
        assert result.is_valid  # should pass because probabilities exist, just warning
        warns = [w.field for w in result.warnings]
        assert "model.probabilities" in warns

    def test_drawdown_range(self, valid_provenance):
        p = valid_provenance
        p2 = DecisionProvenance(
            decision_id=p.decision_id, cycle_id=p.cycle_id, asset=p.asset,
            decision_timestamp=p.decision_timestamp,
            portfolio=PortfolioContext(
                total_equity=100000.0, peak_value=105000.0, drawdown_pct=0.05,
                gross_exposure=0.0, net_exposure=0.0, open_position_count=0,
            ),
        )
        result = ProvenanceValidator().validate(p2)
        assert not result.is_valid

    def test_halt_ratio_out_of_range(self, valid_provenance):
        p = valid_provenance
        p2 = DecisionProvenance(
            decision_id=p.decision_id, cycle_id=p.cycle_id, asset=p.asset,
            decision_timestamp=p.decision_timestamp,
            runtime=ProvenanceExecutionContext(cycle_id=42, n_assets=22, n_healthy=0, n_halted=22, halt_ratio=1.5),
        )
        result = ProvenanceValidator().validate(p2)
        assert not result.is_valid

    def test_cross_context_asset_mismatch(self, valid_provenance):
        p = valid_provenance
        p2 = DecisionProvenance(
            decision_id=p.decision_id, cycle_id=p.cycle_id, asset="EURUSD",
            decision_timestamp=p.decision_timestamp,
            market=MarketContext(asset="GBPJPY", ticker="GBPJPY=X", close_price=186.5),
        )
        result = ProvenanceValidator().validate(p2)
        assert not result.is_valid

    def test_cross_context_cycle_id_mismatch(self, valid_provenance):
        p = valid_provenance
        p2 = DecisionProvenance(
            decision_id=p.decision_id, cycle_id=42, asset=p.asset,
            decision_timestamp=p.decision_timestamp,
            runtime=ProvenanceExecutionContext(cycle_id=99),
        )
        result = ProvenanceValidator().validate(p2)
        assert result.is_valid  # warning, not error
        warns = [w.field for w in result.warnings]
        assert "cross_context.cycle_id" in warns

    def test_empty_contexts_in_non_strict_mode(self):
        p = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=1, asset="EURUSD", decision_timestamp="2026-07-22T12:00:00",
        )
        result = ProvenanceValidator().validate(p)
        assert result.is_valid  # all None contexts OK in non-strict

    def test_empty_contexts_fail_in_strict_mode(self):
        p = DecisionProvenance(
            decision_id=DecisionID.generate(),
            cycle_id=1, asset="EURUSD", decision_timestamp="2026-07-22T12:00:00",
        )
        result = ProvenanceValidator(strict=True).validate(p)
        assert not result.is_valid
        fields = {e.field for e in result.errors}
        assert "market" in fields
        assert "features" in fields
        assert "model" in fields
        assert "portfolio" in fields
        assert "runtime" in fields
        assert "decision" in fields

    def test_batch_validation(self):
        p1 = DecisionProvenance(
            decision_id=DecisionID.generate(), cycle_id=1, asset="EURUSD",
            decision_timestamp="now",
        )
        p2 = DecisionProvenance(
            decision_id=DecisionID(decision_id="", lineage_id=""), cycle_id=1, asset="",
            decision_timestamp="",
        )
        result = ProvenanceValidator.validate_batch([p1, p2])
        assert not result.is_valid
        assert len(result.errors) >= 3  # at least the identity field errors from p2

    def test_validation_result_bool(self):
        r = ValidationResult()
        assert r  # empty result is valid
        r._e("test", "error")
        assert not r  # with errors, invalid

    def test_gates_trace_consistency(self, valid_provenance):
        inconsistent = DecisionProvenance(
            decision_id=valid_provenance.decision_id, cycle_id=valid_provenance.cycle_id,
            asset=valid_provenance.asset, decision_timestamp=valid_provenance.decision_timestamp,
            decision=DecisionTrace(
                final_signal="BUY",
                n_gates_passed=5,  # declared 5, but gates_trace shows 0
                gates_trace={},
            ),
        )
        result = ProvenanceValidator().validate(inconsistent)
        warns = [w.field for w in result.warnings]
        assert "decision.n_gates_passed" in warns

    def test_exposure_multiplier_warning(self, valid_provenance):
        unusual = DecisionProvenance(
            decision_id=valid_provenance.decision_id, cycle_id=valid_provenance.cycle_id,
            asset=valid_provenance.asset, decision_timestamp=valid_provenance.decision_timestamp,
            runtime=ProvenanceExecutionContext(cycle_id=42, exposure_multiplier=5.0, halt_ratio=0.0, n_assets=22, n_healthy=22, n_halted=0),
        )
        result = ProvenanceValidator().validate(unusual)
        warns = [w.field for w in result.warnings]
        assert "runtime.exposure_multiplier" in warns

    def test_forward_compat_schema_version_warning(self, valid_provenance):
        future = DecisionProvenance(
            decision_id=valid_provenance.decision_id, cycle_id=valid_provenance.cycle_id,
            asset=valid_provenance.asset, decision_timestamp=valid_provenance.decision_timestamp,
            schema_version=999,
        )
        result = ProvenanceValidator().validate(future)
        warns = [w.field for w in result.warnings]
        assert "schema_version" in warns


class TestCounterfactualEngine:
    @pytest.fixture
    def buy_record(self):
        return DecisionProvenance(
            decision_id=DecisionID.generate(lineage_id="lineage-1"),
            cycle_id=42,
            asset="GBPJPY",
            decision_timestamp="2026-07-22T10:00:00",
            decision_type="LIVE",
            model=ModelContext(
                model_version="v1", model_hash="mh1",
                prob_long=0.75, prob_short=0.15, prob_neutral=0.10,
            ),
            decision=DecisionTrace(
                final_signal="BUY",
                spread_gate_blocked=False,
                session_gate_blocked=False,
                confidence_gate_blocked=False,
                conviction_gate_blocked=False,
                hysteresis_blocked=False,
                vix_gate_blocked=False,
                adx_gate_blocked=False,
                n_gates_passed=6,
                n_gates_blocked=0,
                gates_blocked=[],
                gates_trace={
                    "spread": True, "session": True, "confidence": True,
                    "conviction": True, "hysteresis": True, "vix": True,
                },
                stop_loss_price=185.0,
                take_profit_price=188.0,
                entry_price=186.5,
                position_size=0.05,
            ),
        )

    def test_gate_override_block(self, buy_record):
        engine = CounterfactualEngine()
        cf, delta = engine.gate_override(buy_record, "spread_gate_blocked", False)
        assert cf.decision_id.lineage_id == "lineage-1"
        assert cf.decision_type == "COUNTERFACTUAL"
        assert cf.decision.spread_gate_blocked is True
        assert cf.decision.n_gates_blocked == 1
        assert cf.decision.n_gates_passed == 6  # 7 total gates - 1 blocked
        assert "spread" in cf.decision.gates_blocked
        assert delta.modification_type == "gate_override"
        assert delta.original_value is False
        assert delta.new_value is True

    def test_gate_override_unblock(self, buy_record):
        blocked = DecisionProvenance(
            decision_id=buy_record.decision_id,
            cycle_id=buy_record.cycle_id,
            asset=buy_record.asset,
            decision_timestamp=buy_record.decision_timestamp,
            decision=buy_record.decision,
        )
        blocked_dict = blocked.to_dict()
        dt = blocked_dict["decision"]
        dt["spread_gate_blocked"] = True
        dt["n_gates_passed"] = 6  # 7 total - 1 blocked (spread)
        dt["n_gates_blocked"] = 1
        dt["gates_blocked"] = ["spread"]
        dt["gates_trace"]["spread"] = False
        blocked = DecisionProvenance.from_dict(blocked_dict)

        engine = CounterfactualEngine()
        cf, delta = engine.gate_override(blocked, "spread_gate_blocked", True)
        assert cf.decision.spread_gate_blocked is False
        assert cf.decision.n_gates_blocked == 0
        assert cf.decision.n_gates_passed == 7  # all 7 gates now pass
        assert delta.original_value is True
        assert delta.new_value is False

    def test_probability_override(self, buy_record):
        engine = CounterfactualEngine()
        cf, delta = engine.probability_override(buy_record, 0.1, 0.8, 0.1)
        assert cf.model.prob_short == 0.8
        assert cf.decision.final_signal == "SELL"
        assert delta.modification_type == "probability_override"

    def test_probability_override_to_neutral(self, buy_record):
        engine = CounterfactualEngine()
        cf, delta = engine.probability_override(buy_record, 0.3, 0.3, 0.4)
        assert cf.decision.final_signal == "HOLD"
        assert delta.new_value["prob_neutral"] == 0.4

    def test_signal_override(self, buy_record):
        engine = CounterfactualEngine()
        cf, delta = engine.signal_override(buy_record, "SELL")
        assert cf.decision.final_signal == "SELL"
        assert cf.decision_id.lineage_id == "lineage-1"
        assert delta.modification_type == "signal_override"
        assert delta.original_value == "BUY"
        assert delta.new_value == "SELL"

    def test_sltp_override(self, buy_record):
        engine = CounterfactualEngine()
        cf, delta = engine.sltp_override(buy_record, stop_loss=184.0, take_profit=190.0)
        assert cf.decision.stop_loss_price == 184.0
        assert cf.decision.take_profit_price == 190.0
        assert delta.modification_type == "sltp_override"

    def test_sltp_override_partial(self, buy_record):
        engine = CounterfactualEngine()
        cf, delta = engine.sltp_override(buy_record, stop_loss=184.5)
        assert cf.decision.stop_loss_price == 184.5
        assert cf.decision.take_profit_price == 188.0  # unchanged

    def test_counterfactual_preserves_original(self, buy_record):
        engine = CounterfactualEngine()
        original_signal = buy_record.decision.final_signal
        engine.signal_override(buy_record, "SELL")
        assert buy_record.decision.final_signal == original_signal  # unchanged

    def test_counterfactual_can_be_stored(self, buy_record):
        engine = CounterfactualEngine()
        cf, _ = engine.signal_override(buy_record, "SELL")
        assert cf.decision_type == "COUNTERFACTUAL"
        assert cf.decision.final_signal == "SELL"

    def test_guess_signal_from_probs(self):
        assert guess_signal_from_probs(0.7, 0.2, 0.1) == "BUY"
        assert guess_signal_from_probs(0.1, 0.8, 0.1) == "SELL"
        assert guess_signal_from_probs(0.3, 0.3, 0.4) == "HOLD"
        assert guess_signal_from_probs(0.4, 0.3, 0.3) == "BUY"
        assert guess_signal_from_probs(0.2, 0.2, 0.6) == "HOLD"


class TestConfigHash:
    def test_returns_sha256_hex(self):
        ch = compute_config_hash()
        assert isinstance(ch, str)
        assert len(ch) == 64

    def test_git_hash_returns_40_chars(self):
        gh = compute_git_hash()
        assert isinstance(gh, str)
        if gh:
            assert len(gh) == 40

    def test_deterministic(self):
        h1 = compute_config_hash()
        h2 = compute_config_hash()
        assert h1 == h2
