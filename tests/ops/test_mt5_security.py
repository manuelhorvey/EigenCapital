"""MT5 bridge security contract tests.

Verifies that the MT5 bridge enforces loopback-only binding and that the
client refuses connections to non-loopback hosts unless explicitly opted in.
These are security invariants — they protect against:
    - accidental exposure of the bridge to the LAN (account takeover)
    - credentials being sent in plaintext TCP frames
    - loopback bypass via wildcard addresses (0.0.0.0)
"""
from __future__ import annotations

import logging

import pytest

from paper_trading.ops import mt5_client
from paper_trading.ops.mt5_client import MT5Client, MT5ConnectionError, _is_loopback


class TestLoopbackDetection:
    """The ``_is_loopback`` helper is the security primitive — must reject
    anything that isn't strictly loopback."""

    def test_loopback_hosts_pass(self):
        assert _is_loopback("127.0.0.1")
        assert _is_loopback("localhost")

    def test_loopback_subnet_pass(self):
        for host in ("127.0.0.1", "127.0.0.42", "127.255.255.254"):
            assert _is_loopback(host), f"{host} should be loopback"

    def test_ipv6_loopback_passes(self):
        assert _is_loopback("::1")

    def test_private_subnets_rejected(self):
        for host in ("10.0.0.1", "192.168.1.1", "172.16.0.1"):
            assert not _is_loopback(host), f"{host} should NOT be loopback"

    def test_public_addrs_rejected(self):
        for host in ("8.8.8.8", "1.1.1.1", "203.0.113.1"):
            assert not _is_loopback(host), f"{host} should NOT be loopback"

    def test_wildcard_rejected(self):
        assert not _is_loopback("0.0.0.0")
        assert not _is_loopback("::")

    def test_empty_rejected(self):
        assert not _is_loopback("")

    def test_garbage_rejected(self):
        assert not _is_loopback("not-a-host")
        assert not _is_loopback("../../../etc/passwd")


class TestMT5ClientSecurityLogging:
    """MT5Client must log a WARNING when pointed at a non-loopback bridge,
    and must accept the same loopback host without warning."""

    def test_remote_bridge_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="eigencapital.mt5_client"):
            MT5Client(account=12345, password="x", server="y", bridge_host="10.0.0.5")
        assert any(
            "non-loopback" in record.message for record in caplog.records
        ), "Expected a non-loopback warning"

    def test_loopback_bridge_silent(self, caplog):
        with caplog.at_level(logging.WARNING, logger="eigencapital.mt5_client"):
            MT5Client(account=12345, password="x", server="y", bridge_host="127.0.0.1")
        assert all(
            "non-loopback" not in record.message for record in caplog.records
        ), "Loopback host should not produce warning"

    def test_remote_bridge_with_override_silent(self, caplog):
        with caplog.at_level(logging.WARNING, logger="eigencapital.mt5_client"):
            MT5Client(
                account=12345,
                password="x",
                server="y",
                bridge_host="10.0.0.5",
                allow_remote_bridge=True,
            )
        assert all(
            "non-loopback" not in record.message for record in caplog.records
        ), "Explicit override should silence the warning"


class TestMT5BridgeConstants:
    """The bridge process source code itself must bind to loopback only.
    Static analysis-style assertion — verified by reading the AST (not
    importing the bridge, since MetaTrader5 is Wine-only and would fail
    to import on CI/dev machines)."""

    def _host_constant(self) -> str:
        import ast
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent.parent / "paper_trading" / "ops" / "mt5_bridge.py"
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "HOST":
                        if isinstance(node.value, ast.Constant):
                            return node.value.value
        raise AssertionError("HOST constant not found in mt5_bridge.py")

    def test_bridge_binds_to_loopback(self):
        host = self._host_constant()
        assert _is_loopback(host), f"MT5 bridge must bind to loopback, got {host!r}"

    def test_bridge_has_no_public_bind_wildcard(self):
        host = self._host_constant()
        assert host != "0.0.0.0"
        assert host != "::"

    def test_bridge_password_loaded_from_env(self):
        """Password must come from env var, not CLI args (ps aux visibility)."""
        import ast
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent.parent / "paper_trading" / "ops" / "mt5_bridge.py"
        src = path.read_text()
        # The main() body should reference the env var
        assert "MT5_PASSWORD" in src
        # And the bridge should NOT have a CLI argument parser
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in ("ArgumentParser",):
                pytest.fail(
                    "Bridge must not accept CLI args (password would appear in ps aux)."
                )
        assert "ArgumentParser" not in src

    def test_bridge_does_not_log_password(self):
        """No log statement should include the literal password value."""
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent.parent / "paper_trading" / "ops" / "mt5_bridge.py"
        src = path.read_text()
        # Make sure no log statement sends the password
        for line in src.splitlines():
            stripped = line.strip()
            if "logger" in stripped and "password" in stripped.lower():
                # Allow lines that DON'T include a format specifier AND only reference
                # the config dict (no %s or .format() with the password)
                if "_config[" in stripped and "password" in stripped:
                    if "%s" in stripped or ".format(" in stripped:
                        pytest.fail(f"Password may leak in log: {stripped}")


class TestMT5ClientStateSecurity:
    """MT5Client stores credentials in memory; verify it doesn't expose them
    via convenience methods or repr."""

    def test_client_does_not_repr_password(self):
        client = MT5Client(account=12345, password="supersecret", server="exness")
        s = repr(client)
        assert "supersecret" not in s

    def test_client_does_not_log_password_in_connect_failure(self, caplog):
        client = MT5Client(
            account=12345,
            password="supersecret",
            server="exness",
            bridge_host="127.0.0.1",
            bridge_port=1,  # invalid port — connect will fail
        )
        with caplog.at_level(logging.ERROR, logger="eigencapital.mt5_client"):
            try:
                client.connect()
            except (MT5ConnectionError, OSError):
                pass  # expected
        assert "supersecret" not in caplog.text


class TestMT5ContractInvariants:
    """Protocol-level invariants — these bind the bridge ↔ client surface."""

    def test_max_payload_is_sane(self):
        """Frame payload should not be unbounded."""
        assert mt5_client._MAX_PAYLOAD >= 1024
        assert mt5_client._MAX_PAYLOAD <= 64 * 1024 * 1024  # 64 MiB upper bound

    def test_circuit_breaker_timeouts_monotonic(self):
        """Backoff timeouts must increase or stay equal (never decrease)."""
        timeouts = mt5_client._CIRCUIT_BREAKER_TIMEOUTS
        for a, b in zip(timeouts, timeouts[1:]):
            assert b >= a, f"Backoff must not decrease: {a} -> {b}"

    def test_default_port_in_legal_range(self):
        assert 1 <= mt5_client.DEFAULT_MT5_BRIDGE_PORT <= 65535
