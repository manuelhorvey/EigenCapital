"""Configuration Consistency Tests — verify single source of truth.

These tests ensure that:
1. All safety-critical parameters come from config.toml
2. No hardcoded values in execution scripts disagree with config
3. The live_risk envelope matches capital boundaries
4. Fingerprint verification works end-to-end
5. The dead `[risk]` table stays annotated as dead/legacy and unparsed (H-10)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from eigencapital.config import (
    LiveRiskConfig,
    load_config,
    normalize_asset_class,
    validate_config_consistency,
)
from eigencapital.fidelity.r4_manifest import R4ConfigManifest

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestConfigLoading:
    """Verify configuration loads correctly from TOML."""

    def test_production_config_loads(self):
        """Production config must load without error."""
        os.environ["MT5_ACCOUNT_ID"] = "436921728"
        os.environ["MT5_SERVER"] = "Exness-MT5Trial9"
        config = load_config("production")
        assert config.environment == "production"
        assert config.broker.account_id == "436921728"
        assert config.broker.broker_name == "exness"

    def test_production_config_fails_without_account_id(self):
        """Production config must show visible failure if MT5_ACCOUNT_ID is unset."""
        os.environ.pop("MT5_ACCOUNT_ID", None)
        os.environ.pop("MT5_SERVER", None)
        config = load_config("production")
        errors = validate_config_consistency(config)
        assert any("empty in production config" in e for e in errors), (
            f"Expected visible failure about empty account_id, got: {errors}"
        )

    def test_live_risk_config_loads(self):
        """live_risk config must load expected limits.

        T0 (forensic audit 2026-09-13): max_position_notional aligned 2500 →
        5000, matching capital.max_position_size — the value the sizing path
        has always used. The 2500 was a dead limit (never enforced) and sat
        below XAUUSD/US30 min-lot cost, making it unenforceable as-written.
        """
        config = load_config("production")
        lr = config.live_risk
        assert lr.max_concurrent_positions == 20
        assert lr.max_position_notional == 5000.0
        assert lr.max_order_notional == 5000.0
        assert lr.max_daily_loss == 250.0
        assert lr.min_equity == 4000.0
        assert lr.t0_equity == 5010.94

    def test_strategy_config_loads_r4_params(self):
        """strategy config must load frozen R4 parameters."""
        config = load_config("production")
        st = config.strategy
        assert st.signal_lookback_long == 252
        assert st.skip_months == 1
        assert st.vol_lookback_signal == 60
        assert st.risk_lookback == 20

    def test_execution_config_loads_max_orders(self):
        """execution config must load max_orders_per_cycle."""
        config = load_config("production")
        assert config.execution.max_orders_per_cycle == 20


class TestLiveRiskFingerprint:
    """Verify live risk envelope can be fingerprinted."""

    def test_fingerprint_deterministic(self):
        """Same config produces same fingerprint."""
        lr1 = LiveRiskConfig()
        lr2 = LiveRiskConfig()
        assert lr1.compute_fingerprint() == lr2.compute_fingerprint()

    def test_fingerprint_changes_on_value_change(self):
        """Changing any value changes the fingerprint."""
        lr1 = LiveRiskConfig(max_daily_loss=250.0)
        lr2 = LiveRiskConfig(max_daily_loss=300.0)
        assert lr1.compute_fingerprint() != lr2.compute_fingerprint()

    def test_fingerprint_immutable(self):
        """LiveRiskConfig is frozen."""
        lr = LiveRiskConfig()
        with pytest.raises(AttributeError):
            lr.max_daily_loss = 999.0


class TestConfigVsScriptConsistency:
    """Verify that config values match what the rebalance loop uses."""

    def test_eligible_symbols_from_config(self):
        """Eligible symbols should be derived from broker config."""
        config = load_config("production")
        eligible = [sym for sym, cls in config.broker.allowed_symbols.items() if not cls.endswith("_excluded")]
        # Must include core forex pairs and USTEC
        for sym in ["EURUSD", "GBPUSD", "AUDUSD", "USDCHF", "USTEC"]:
            assert sym in eligible, f"{sym} missing from eligible symbols"

    def test_hk50_jp225_eligible_as_indices(self):
        """HK50/JP225 (admitted 2026-09-27) must be eligible and classified as indices.

        Regression guard: neither symbol may be silently dropped, misclassified
        as FX/crypto/metals/energy, or routed into an exclusion list.
        """
        config = load_config("production")
        allowed = config.broker.allowed_symbols
        assert allowed.get("HK50") == "indices", f"HK50 class = {allowed.get('HK50')!r}"
        assert allowed.get("JP225") == "indices", f"JP225 class = {allowed.get('JP225')!r}"
        eligible = {sym for sym, cls in allowed.items() if not cls.endswith("_excluded")}
        assert "HK50" in eligible, "HK50 absent from eligible universe"
        assert "JP225" in eligible, "JP225 absent from eligible universe"

    def test_allowed_symbols_no_duplicates_and_all_classified(self):
        """Every allowed symbol must have a non-empty classification (fail closed
        against unclassified/unparsed universe entries)."""
        config = load_config("production")
        allowed = config.broker.allowed_symbols
        symbols = list(allowed.keys())
        assert len(symbols) == len(set(symbols)), "duplicate symbols in allowed_symbols"
        unclassified = [s for s, cls in allowed.items() if not str(cls).strip()]
        assert unclassified == [], f"symbols without asset class: {unclassified}"

    def test_spread_gates_share_one_config_source(self):
        """All three spread gates read the same per-class tables from config.

        The live entry gate (relative, non-FX), account readiness §6 and
        pre-trading PT-BROKER-05 (MT5 points) must not carry their own
        hardcoded tolerance tables — otherwise XNGUSD can be allowed by one
        gate and blocked by another.
        """
        broker = load_config("production").broker

        # XNGUSD quoted 0.2193% on 2026-09-27 and was skipped by the 0.15%
        # default; the configured energy cap must clear that quote.
        assert broker.spread_class_of("XNGUSD") == "energy"
        assert broker.relative_spread_limit("energy") == pytest.approx(0.0030)
        assert broker.relative_spread_limit("energy") > 0.002193

        # Every class actually present in the universe has a points tolerance.
        classes = {normalize_asset_class(cls) for cls in broker.allowed_symbols.values()}
        missing = sorted(c for c in classes if c not in broker.max_spread_points_by_class)
        assert missing == [], f"classes without a points spread limit: {missing}"
        assert broker.points_spread_limit("energy") == 50

        # Only energy is widened — every other class keeps the 0.15% default.
        for cls in ("indices", "metals", "crypto", "forex_excluded"):
            assert broker.relative_spread_limit(cls) == pytest.approx(broker.max_spread), cls

    def test_symbol_mapping_fingerprint_reflects_universe(self):
        """compute_symbol_mapping_fingerprint must change when the universe changes
        (EC-AUD-009 drift detection covers the HK50/JP225 admission)."""
        from eigencapital.config import compute_symbol_mapping_fingerprint

        config = load_config("production")
        base_fp = compute_symbol_mapping_fingerprint(config)
        drifted = dict(config.broker.allowed_symbols)
        drifted.pop("HK50")
        import dataclasses

        drifted_config = dataclasses.replace(config, broker=dataclasses.replace(config.broker, allowed_symbols=drifted))
        assert compute_symbol_mapping_fingerprint(drifted_config) != base_fp

    def test_risk_envelope_from_config(self):
        """RiskEnvelope values must match live_risk config.

        T0: notionals aligned to the capital section (see
        test_live_risk_config_loads); the alignment itself is enforced by
        validate_config_consistency and tested in test_t0_sizing.py.
        """
        config = load_config("production")
        lr = config.live_risk
        assert lr.max_concurrent_positions == 20
        assert lr.max_position_notional == 5000.0
        assert lr.max_daily_loss == 250.0
        assert lr.min_equity == 4000.0
        assert lr.t0_equity == 5010.94

    def test_capital_limits_from_config(self):
        """Capital limits must match config."""
        config = load_config("production")
        assert config.capital.max_equity == 20000.0
        assert config.capital.max_position_size == 5000.0
        assert config.capital.max_concurrent_positions == 20

    def test_no_discrepancy_between_live_risk_and_capital(self):
        """live_risk.max_concurrent_positions must equal capital.max_concurrent_positions."""
        config = load_config("production")
        assert config.live_risk.max_concurrent_positions == config.capital.max_concurrent_positions, (
            f"Discrepancy: live_risk={config.live_risk.max_concurrent_positions} "
            f"vs capital={config.capital.max_concurrent_positions}"
        )


class TestR4ManifestIntegrity:
    """Verify R4 manifest fingerprint is stable."""

    def test_manifest_fingerprint_unchanged(self):
        """R4 manifest fingerprint must match the frozen value."""
        manifest = R4ConfigManifest()
        fp = manifest.compute_identity()
        assert fp == "aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb"

    def test_manifest_strategy_version(self):
        """Strategy version must be R4.0."""
        manifest = R4ConfigManifest()
        assert manifest.strategy_version == "R4.0"

    def test_manifest_config_fingerprint_matches_toml(self):
        """Config manifest_fingerprint must match R4ConfigManifest."""
        config = load_config("production")
        manifest = R4ConfigManifest()
        assert config.strategy.manifest_fingerprint == manifest.compute_identity()


class TestDeadRiskTableAnnotation:
    """H-10 guard: the `[risk]` TOML table is dead/legacy and must stay that way.

    (a) EVERY config file under configs/ (discovered by glob, not a hardcoded
        list) either has no `[risk]` table at all, or carries a dead/legacy
        marker comment directly above it — so a newly added config cannot
        silently reintroduce an unannotated one.
    (b) No module under src/eigencapital parses a TOML section named `risk`, so
        nobody can silently wire it up without updating this guard and the
        config annotations.

    Human decision (FINDINGS.md, 2026-09-28): annotate only — NO wiring change.
    """

    # Glob-based discovery: every file under configs/, whatever it is named.
    CONFIG_FILES = tuple(sorted(path for path in (REPO_ROOT / "configs").rglob("*") if path.is_file()))
    CONFIG_IDS = tuple(str(path.relative_to(REPO_ROOT)) for path in CONFIG_FILES)
    # Marker text that must appear in the comment block directly above [risk].
    DEAD_MARKERS = ("dead", "legacy", "never parsed", "no effect")

    @staticmethod
    def _comment_block_above(lines: list[str], header: str) -> str:
        """Contiguous comment block directly above `header` (blank lines allowed)."""
        try:
            idx = next(i for i, line in enumerate(lines) if line.strip() == header)
        except StopIteration:
            return ""
        block: list[str] = []
        i = idx - 1
        while i >= 0:
            stripped = lines[i].lstrip()
            if stripped.startswith("#"):
                block.append(lines[i])
            elif stripped:
                break
            i -= 1
        return "\n".join(reversed(block))

    def test_config_glob_discovers_files(self) -> None:
        """The glob must actually find configs/, else every other check is inert."""
        assert self.CONFIG_FILES, "configs/ glob found no files — the H-10 guard is inert"
        files_with_risk = [
            path
            for path in self.CONFIG_FILES
            if any(line.strip() == "[risk]" for line in path.read_text(encoding="utf-8").splitlines())
        ]
        assert files_with_risk, (
            "no config under configs/ defines a [risk] table anymore — if the table "
            "was deleted rather than annotated, that is an H-10 decision change and "
            "this guard must be revisited"
        )

    @pytest.mark.parametrize("config_path", CONFIG_FILES, ids=CONFIG_IDS)
    def test_risk_table_is_annotated_dead(self, config_path: Path) -> None:
        """If a config has `[risk]`, it must carry dead/legacy markers above it.

        A file with no `[risk]` table vacuously satisfies the guard.
        """
        lines = config_path.read_text(encoding="utf-8").splitlines()
        if not any(line.strip() == "[risk]" for line in lines):
            return  # no [risk] table in this config: nothing to annotate (H-10 vacuous here)
        block = self._comment_block_above(lines, "[risk]").lower()
        missing = [marker for marker in self.DEAD_MARKERS if marker not in block]
        assert not missing, (
            f"{config_path.relative_to(REPO_ROOT)}: the [risk] table is missing "
            f"dead/legacy marker text {missing} in the comment block directly "
            "above it (H-10 — this table is parsed by nothing; editing it has no effect)"
        )

    def test_no_module_parses_toml_risk_section(self) -> None:
        """No module under src/eigencapital may read a TOML section named `risk`."""
        # Cheap source scan: (1) a dict fetch of the section key anywhere under
        # src, (2) a subscript fetch inside a module that actually parses TOML.
        section_get = re.compile(r"""\.get\(\s*['"]risk['"]""")
        section_subscript = re.compile(r"""\[\s*['"]risk['"]\s*\]""")
        toml_parser = re.compile(r"""tomllib|import toml\b""")

        src_root = REPO_ROOT / "src" / "eigencapital"
        offenders: list[str] = []
        for path in sorted(src_root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            rel = path.relative_to(REPO_ROOT)
            if section_get.search(source):
                offenders.append(f'{rel}: .get("risk", ...)')
            if toml_parser.search(source) and section_subscript.search(source):
                offenders.append(f'{rel}: data["risk"] in a TOML-parsing module')

        assert not offenders, (
            "H-10: the [risk] TOML table is dead/legacy and must remain unparsed "
            "(see the DEAD / LEGACY annotation above it in every config under "
            "configs/). If wiring it up is now intentional, "
            f"update those annotations AND this guard. Offenders: {offenders}"
        )
