"""Tests for shared/vault_secrets.py — VaultSecretsProvider."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from shared.vault_secrets import (
    VaultConfig,
    VaultSecretsProvider,
    clear_default_provider,
    get_vault_provider,
    resolve_mt5_credentials,
)


def _make_provider(config: VaultConfig | None = None) -> VaultSecretsProvider:
    """Return a VaultSecretsProvider with optional config (bypasses singleton)."""
    cfg = config or VaultConfig(enabled=False)
    return VaultSecretsProvider(cfg)


# ── VaultConfig.from_env() ─────────────────────────────────────────


class TestVaultConfig:
    def test_defaults_when_env_not_set(self):
        cfg = VaultConfig.from_env()
        assert cfg.url == "http://127.0.0.1:8200"
        assert cfg.token == ""
        assert cfg.mount_point == "secret"
        assert cfg.path == "eigencapital/mt5"
        assert cfg.enabled is False
        assert cfg.timeout_seconds == 5

    def test_reads_from_env(self):
        with patch.dict(
            os.environ,
            {
                "VAULT_ADDR": "https://vault.example.com:8200",
                "VAULT_TOKEN": "hvs.test-token",
                "VAULT_MOUNT_POINT": "my-kv",
                "VAULT_SECRET_PATH": "my-app/secrets",
                "VAULT_ENABLED": "true",
                "VAULT_TIMEOUT": "10",
            },
            clear=True,
        ):
            cfg = VaultConfig.from_env()
            assert cfg.url == "https://vault.example.com:8200"
            assert cfg.token == "hvs.test-token"
            assert cfg.mount_point == "my-kv"
            assert cfg.path == "my-app/secrets"
            assert cfg.enabled is True
            assert cfg.timeout_seconds == 10


# ── VaultSecretsProvider (no Vault) ────────────────────────────────


class TestVaultSecretsProviderNoVault:
    """Tests when Vault is disabled or unreachable — env var fallback only."""

    def test_get_mt5_credentials_from_env(self):
        with patch.dict(
            os.environ,
            {
                "MT5_ACCOUNT": "12345",
                "MT5_PASSWORD": "secret-pw",
                "MT5_SERVER": "Exness-MT5Trial",
            },
            clear=True,
        ):
            provider = _make_provider()
            creds = provider.get_mt5_credentials()
            assert creds["account"] == 12345
            assert creds["password"] == "secret-pw"
            assert creds["server"] == "Exness-MT5Trial"

    def test_get_mt5_credentials_missing_env(self):
        with patch.dict(os.environ, {}, clear=True):
            provider = _make_provider()
            creds = provider.get_mt5_credentials()
            assert creds == {}

    def test_get_mt5_credentials_partial_env(self):
        with patch.dict(os.environ, {"MT5_ACCOUNT": "99999"}, clear=True):
            provider = _make_provider()
            creds = provider.get_mt5_credentials()
            assert creds.get("account") == 99999
            assert "password" not in creds
            assert "server" not in creds

    def test_get_api_token_from_env(self):
        with patch.dict(os.environ, {"EIGENCAPITAL_API_TOKEN": "abc-token-123"}, clear=True):
            provider = _make_provider()
            token = provider.get_api_token()
            assert token == "abc-token-123"

    def test_get_api_token_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            provider = _make_provider()
            token = provider.get_api_token()
            assert token == ""


# ── VaultSecretsProvider (with mocked Vault) ────────────────────────


class TestVaultSecretsProviderWithVault:
    """Tests with Vault enabled and a mocked hvac client."""

    def _mock_hvac_client(self, data: dict | None = None):
        """Return a MagicMock hvac client with KV v2 support."""
        client = MagicMock()
        client.is_authenticated.return_value = True
        if data is not None:
            client.secrets.kv.v2.read_secret_version.return_value = {"data": {"data": data}}
        else:
            client.secrets.kv.v2.read_secret_version.side_effect = KeyError("Secret path not found")
        return client

    def test_get_mt5_credentials_from_vault(self):
        config = VaultConfig(enabled=True, path="eigencapital/mt5")
        provider = _make_provider(config)
        provider._get_hvac = MagicMock(return_value=MagicMock())  # noqa: SLF001
        provider._client = self._mock_hvac_client(
            data={"account": "12345", "password": "vault-pw", "server": "Exness-Prod"}
        )

        creds = provider.get_mt5_credentials()
        assert creds["account"] == 12345
        assert creds["password"] == "vault-pw"
        assert creds["server"] == "Exness-Prod"

    def test_vault_preferred_over_env(self):
        """When Vault is enabled, Vault values should take precedence over env vars."""
        config = VaultConfig(enabled=True, path="eigencapital/mt5")
        provider = _make_provider(config)
        provider._get_hvac = MagicMock(return_value=MagicMock())  # noqa: SLF001
        provider._client = self._mock_hvac_client(
            data={"account": "99999", "password": "vault-secret", "server": "Vault-Server"}
        )

        with patch.dict(
            os.environ,
            {"MT5_PASSWORD": "env-secret"},
            clear=True,
        ):
            creds = provider.get_mt5_credentials()
            # Vault values should win
            assert creds["account"] == 99999
            assert creds["password"] == "vault-secret"
            assert creds["server"] == "Vault-Server"

    def test_fallback_to_env_when_vault_fails(self):
        """When Vault authentication fails, fall back to env vars."""
        config = VaultConfig(enabled=True)
        provider = _make_provider(config)
        provider._get_hvac = MagicMock(return_value=MagicMock())  # noqa: SLF001
        provider._client = self._mock_hvac_client()  # no data, will fail

        with patch.dict(
            os.environ,
            {"MT5_ACCOUNT": "77777", "MT5_PASSWORD": "env-pw", "MT5_SERVER": "Env-Server"},
            clear=True,
        ):
            creds = provider.get_mt5_credentials()
            assert creds.get("account") == 77777
            assert creds.get("password") == "env-pw"

    def test_vault_cache_hit(self):
        """Cached values should be returned without calling Vault again."""
        config = VaultConfig(enabled=True, path="eigencapital/mt5")
        provider = _make_provider(config)
        provider._get_hvac = MagicMock(return_value=MagicMock())  # noqa: SLF001
        provider._client = self._mock_hvac_client(data={"account": "11111"})

        # First call — hits Vault
        creds1 = provider.get_mt5_credentials()
        assert creds1["account"] == 11111

        # Second call — should use cache, not Vault
        creds2 = provider.get_mt5_credentials()
        assert creds2["account"] == 11111
        # read_secret_version should only have been called once
        provider._client.secrets.kv.v2.read_secret_version.assert_called_once()

    def test_invalidate_cache(self):
        config = VaultConfig(enabled=True, path="eigencapital/mt5")
        provider = _make_provider(config)
        provider._get_hvac = MagicMock(return_value=MagicMock())  # noqa: SLF001
        provider._client = self._mock_hvac_client(data={"account": "11111"})

        provider.get_mt5_credentials()
        provider.invalidate_cache()

        # After invalidation, should call Vault again
        provider._client = self._mock_hvac_client(data={"account": "22222"})
        creds = provider.get_mt5_credentials()
        assert creds["account"] == 22222

    def test_is_vault_available_true(self):
        config = VaultConfig(enabled=True)
        provider = _make_provider(config)
        provider._get_hvac = MagicMock(return_value=MagicMock())  # noqa: SLF001
        provider._client = self._mock_hvac_client(data={"account": "1"})

        assert provider.is_vault_available is True

    def test_is_vault_available_false_when_disabled(self):
        provider = _make_provider(VaultConfig(enabled=False))
        assert provider.is_vault_available is False

    def test_get_generic_secret(self):
        config = VaultConfig(enabled=True)
        provider = _make_provider(config)
        provider._get_hvac = MagicMock(return_value=MagicMock())  # noqa: SLF001
        provider._client = self._mock_hvac_client(data={"webhook_url": "https://hooks.example.com"})

        data = provider.get_generic_secret("monitoring/slack")
        assert data is not None
        assert data["webhook_url"] == "https://hooks.example.com"

    def test_get_api_token_from_vault(self):
        config = VaultConfig(enabled=True, path="eigencapital/mt5")
        provider = _make_provider(config)
        provider._get_hvac = MagicMock(return_value=MagicMock())  # noqa: SLF001
        provider._client = self._mock_hvac_client(data={"api_token": "vault-token-abc"})

        token = provider.get_api_token()
        assert token == "vault-token-abc"


# ── resolve_mt5_credentials() ──────────────────────────────────────


class TestResolveMt5Credentials:
    def test_with_yaml_fallback(self):
        """When neither Vault nor env vars provide values, use YAML defaults."""
        with patch.dict(os.environ, {}, clear=True):
            creds = resolve_mt5_credentials(
                config_data={"account": 55555, "password": "yaml-pw", "server": "YAML-Server"}
            )
            assert creds.get("account") == 55555
            assert creds.get("password") == "yaml-pw"
            assert creds.get("server") == "YAML-Server"

    def test_with_env_overriding_yaml(self):
        """Env vars take precedence over YAML defaults when Vault is disabled."""
        with patch.dict(
            os.environ,
            {"MT5_ACCOUNT": "11111", "MT5_PASSWORD": "env-pw"},
            clear=True,
        ):
            creds = resolve_mt5_credentials(config_data={"account": 99999, "server": "YAML-Server"})
            assert creds.get("account") == 11111
            assert creds.get("password") == "env-pw"
            # server should fall back to YAML since no env var
            assert creds.get("server") == "YAML-Server"

    def test_clear_default_provider(self):
        clear_default_provider()
        p1 = get_vault_provider()
        p2 = get_vault_provider()
        assert p1 is p2  # singleton
        clear_default_provider()
        p3 = get_vault_provider()
        assert p3 is not p1  # new instance after clear
