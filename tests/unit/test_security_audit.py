"""Security audit tests for production trading system."""

import importlib
import importlib.util
import inspect
import re
from pathlib import Path

import pytest


class TestNoHardcodedCredentials:
    @staticmethod
    def _scan_py_files():
        src_dir = Path(__file__).resolve().parent.parent.parent / "src"
        yield from src_dir.rglob("*.py")

    def test_no_hardcoded_passwords(self):
        pattern = re.compile(r"""(?:password|passwd)\s*=\s*["'][^"']+["']""", re.IGNORECASE)
        violations = []
        for py_file in self._scan_py_files():
            if "test_" in py_file.name:
                continue
            content = py_file.read_text(errors="replace")
            for match in pattern.finditer(content):
                line_no = content[: match.start()].count("\n") + 1
                violations.append(f"{py_file}:{line_no}: {match.group()[:60]}")
        assert not violations, "Hardcoded passwords:\n" + "\n".join(violations)

    def test_no_hardcoded_api_keys(self):
        pattern = re.compile(r"""(?:api_key|apikey|api_secret)\s*=\s*["'][A-Za-z0-9_\-]{20,}["']""", re.IGNORECASE)
        violations = []
        for py_file in self._scan_py_files():
            if "test_" in py_file.name or ".env" in py_file.name:
                continue
            content = py_file.read_text(errors="replace")
            for match in pattern.finditer(content):
                line_no = content[: match.start()].count("\n") + 1
                violations.append(f"{py_file}:{line_no}")
        assert not violations, "Hardcoded API keys:\n" + "\n".join(violations)

    @pytest.mark.skipif(not importlib.util.find_spec("mt5linux"), reason="mt5linux not installed (CI environment)")
    def test_telegram_tokens_from_env(self):
        monitor = importlib.import_module("scripts.r4_monitor")
        source = inspect.getsource(monitor)
        assert "os.environ" in source or "os.getenv" in source


class TestAuditLogSecurity:
    def test_audit_log_no_credentials(self):
        from eigencapital.live.risk_enforcement import RiskEnforcer, RiskEnvelope

        enforcer = RiskEnforcer(RiskEnvelope())
        enforcer.check_all(broker_positions=[], account_equity=5000.0, account_free_margin=3000.0)
        for entry in enforcer.get_audit_log():
            entry_str = str(entry).lower()
            assert "password" not in entry_str
            assert "secret" not in entry_str
            assert "api_key" not in entry_str

    def test_fingerprint_log_no_secrets(self):
        from eigencapital.fidelity.r4_manifest import R4ConfigManifest
        from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier
        from eigencapital.risk.policy import RiskPolicy

        verifier = FingerprintVerifier(manifest=R4ConfigManifest(), risk_policy=RiskPolicy())
        verifier.verify_all()
        for entry in verifier.verification_log:
            entry_str = str(entry).lower()
            assert "password" not in entry_str
            assert "secret" not in entry_str


class TestSecurityBoundaries:
    def test_research_cannot_submit_orders(self):
        research_dir = Path(__file__).resolve().parent.parent.parent / "src" / "eigencapital" / "research"
        if not research_dir.exists():
            pytest.skip("No research directory")
        violations = []
        for py_file in research_dir.rglob("*.py"):
            content = py_file.read_text(errors="replace")
            if "from eigencapital.execution" in content or "from eigencapital.live" in content:
                violations.append(str(py_file))
        assert not violations, "Research imports live execution:\n" + "\n".join(violations)

    def test_live_cannot_retrain(self):
        live_dir = Path(__file__).resolve().parent.parent.parent / "src" / "eigencapital" / "live"
        if not live_dir.exists():
            pytest.skip("No live directory")
        violations = []
        for py_file in live_dir.rglob("*.py"):
            source = py_file.read_text(errors="replace")
            for forbidden in ["sklearn", "keras", "tensorflow", "torch"]:
                if f"import {forbidden}" in source or f"from {forbidden}" in source:
                    violations.append(f"{py_file}: imports {forbidden}")
        assert not violations, "Live code imports training:\n" + "\n".join(violations)


class TestConfigurationManifest:
    def test_manifest_fingerprint_deterministic(self):
        from eigencapital.production.security import ConfigurationManifest

        m1 = ConfigurationManifest(strategy_config_hash="abc123", risk_config_hash="def456")
        m2 = ConfigurationManifest(strategy_config_hash="abc123", risk_config_hash="def456")
        assert m1.to_dict() == m2.to_dict()

    def test_manifest_tamper_detection(self):
        from eigencapital.production.security import ConfigurationManifest

        m1 = ConfigurationManifest(strategy_config_hash="abc123")
        m2 = ConfigurationManifest(strategy_config_hash="xyz789")
        assert m1.to_dict() != m2.to_dict()


class TestFilePermissions:
    def test_env_example_not_executable(self):
        env_file = Path(__file__).resolve().parent.parent.parent / ".env.example"
        if not env_file.exists():
            pytest.skip("No .env.example")
        mode = env_file.stat().st_mode
        assert not (mode & 0o001)

    def test_config_files_not_executable(self):
        config_dir = Path(__file__).resolve().parent.parent.parent / "configs"
        if not config_dir.exists():
            pytest.skip("No configs directory")
        for config_file in config_dir.rglob("*"):
            if config_file.is_file():
                assert not (config_file.stat().st_mode & 0o111), f"Executable: {config_file}"
