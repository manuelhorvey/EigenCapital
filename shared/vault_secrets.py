"""VaultSecretsProvider — fetch secrets from HashiCorp Vault with env-var fallback.

Supports KV v2 engine (the standard for modern Vault deployments).
Falls back to environment variables when Vault is unavailable (development).

Usage:
    provider = VaultSecretsProvider()
    creds = provider.get_mt5_credentials()
    # Returns {"account": 12345, "password": "...", "server": "..."}
"""

from __future__ import annotations

import logging
import os
import threading
import time
import typing
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("eigencapital.vault_secrets")

_VAULT_CACHE_TTL = 300.0  # 5 minutes


@dataclass
class VaultConfig:
    """Vault connection parameters.

    Reads from environment variables with sensible defaults for local dev.
    """

    url: str = "http://127.0.0.1:8200"
    token: str = ""
    mount_point: str = "secret"
    path: str = "eigencapital/mt5"
    enabled: bool = False
    timeout_seconds: int = 5
    cache_ttl: float = _VAULT_CACHE_TTL

    @classmethod
    def from_env(cls) -> VaultConfig:
        return cls(
            url=os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200"),
            token=os.environ.get("VAULT_TOKEN", ""),
            mount_point=os.environ.get("VAULT_MOUNT_POINT", "secret"),
            path=os.environ.get("VAULT_SECRET_PATH", "eigencapital/mt5"),
            enabled=os.environ.get("VAULT_ENABLED", "").lower() in ("1", "true", "yes"),
            timeout_seconds=int(os.environ.get("VAULT_TIMEOUT", "5")),
        )


class VaultSecretsProvider:
    """Thread-safe secrets provider backed by HashiCorp Vault KV v2.

    Falls back to environment variables when Vault is disabled or unreachable.
    Results are cached with a configurable TTL to avoid hammering Vault.
    """

    def __init__(self, config: VaultConfig | None = None) -> None:
        self._config = config or VaultConfig.from_env()
        self._client_lock = threading.Lock()
        self._client: Any = None
        self._cache: dict[str, tuple[Any, float]] = {}
        self._cache_lock = threading.Lock()
        self._hvac_module: Any = None  # cached hvac module or None

    # ── Connection management ─────────────────────────────────────────

    def _get_hvac(self) -> Any:
        """Lazy import hvac, caching the module object.

        Returns the hvac module or None if not installed.
        """
        if self._hvac_module is not None:
            return self._hvac_module
        try:
            import hvac

            self._hvac_module = hvac
            return hvac
        except ImportError:
            self._hvac_module = None
            logger.warning("hvac library not installed. Vault integration disabled. Install with: pip install hvac")
            return None

    def _ensure_client(self) -> Any | None:
        """Return an authenticated hvac.Client, or None if Vault is unavailable.

        Thread-safe: only one thread creates the client; others wait.
        """
        hvac = self._get_hvac()
        if hvac is None:
            return None

        # Fast path: already connected
        if self._client is not None:
            return self._client

        with self._client_lock:
            # Double-check after acquiring lock
            if self._client is not None:
                return self._client
            try:
                client = hvac.Client(
                    url=self._config.url,
                    token=self._config.token,
                    timeout=self._config.timeout_seconds,
                )
                if not client.is_authenticated():
                    logger.warning(
                        "Vault authentication failed for %s — falling back to env vars",
                        self._config.url,
                    )
                    return None
                self._client = client
                logger.info(
                    "Vault connected: %s mount=%s path=%s",
                    self._config.url,
                    self._config.mount_point,
                    self._config.path,
                )
                return client
            except (ConnectionError, TimeoutError, OSError) as exc:
                logger.warning(
                    "Vault connection failed (%s) — falling back to env vars",
                    exc,
                )
                return None

    # ── Secret resolution ─────────────────────────────────────────────

    def _cache_key(self, path: str, mount_point: str) -> str:
        """Build a unique cache key for a Vault path."""
        return f"{mount_point}/{path}"

    def _read_secret(self, path: str | None = None, mount_point: str | None = None) -> dict[str, Any] | None:
        """Read a secret from Vault KV v2 with caching.

        Path and mount_point default to the instance config values.
        Returns the 'data' dict (the secret key-value pairs inside the
        KV v2 data envelope), or None if Vault is unavailable.
        """
        p = path or self._config.path
        mp = mount_point or self._config.mount_point
        now = time.monotonic()
        ck = self._cache_key(p, mp)

        with self._cache_lock:
            cached = self._cache.get(ck)
            if cached is not None and now - cached[1] < self._config.cache_ttl:
                return typing.cast(dict[str, Any] | None, cached[0])

        client = self._ensure_client()
        if client is None:
            return None

        try:
            response = typing.cast(
                dict[str, Any],
                client.secrets.kv.v2.read_secret_version(
                    path=p,
                    mount_point=mp,
                ),
            )
            data: dict[str, Any] = response.get("data", {}).get("data", {})
            with self._cache_lock:
                self._cache[ck] = (data, now)
            return data
        except (KeyError, ConnectionError, TimeoutError, OSError) as exc:
            logger.warning("Vault read failed for %s/%s: %s", mp, p, exc)
            return None

    # ── MT5 credential resolution ─────────────────────────────────────

    def get_mt5_credentials(self) -> dict[str, Any]:
        """Return MT5 credentials dict with keys: account, password, server.

        Resolution order:
          1. Vault KV v2 (if enabled and reachable)
          2. Environment variables (MT5_ACCOUNT, MT5_PASSWORD, MT5_SERVER)

        Returns only non-empty values so the caller can merge with defaults.
        ``account`` is always returned as an int when present.
        """
        result: dict[str, Any] = {}

        # 1. Try Vault
        if self._config.enabled:
            vault_data = self._read_secret()
            if vault_data:
                for key, env_key in [
                    ("account", "MT5_ACCOUNT"),
                    ("password", "MT5_PASSWORD"),
                    ("server", "MT5_SERVER"),
                ]:
                    val = vault_data.get(key) or vault_data.get(env_key)
                    if val:
                        result[key] = int(val) if key == "account" else val
                if result:
                    logger.info(
                        "Resolved MT5 credentials from Vault (%s)",
                        ", ".join(result.keys()),
                    )
                    return result

        # 2. Fall back to env vars
        env_account = os.environ.get("MT5_ACCOUNT")
        env_password = os.environ.get("MT5_PASSWORD")
        env_server = os.environ.get("MT5_SERVER")
        if env_account:
            try:
                result["account"] = int(env_account)
            except (ValueError, TypeError):
                logger.warning("MT5_ACCOUNT env var is not a valid integer: %s", env_account)
        if env_password:
            result["password"] = env_password
        if env_server:
            result["server"] = env_server
        if result:
            source = "Vault" if self._config.enabled else "env vars"
            logger.debug("Resolved MT5 credentials from %s", source)

        return result

    def get_api_token(self) -> str:
        """Return the dashboard API token from Vault or env var.

        Resolution order:
          1. Vault KV v2 (from 'api_token' key at the configured path)
          2. EIGENCAPITAL_API_TOKEN env var
        """
        if self._config.enabled:
            vault_data = self._read_secret()
            if vault_data:
                token: str = vault_data.get("api_token", "")
                if token:
                    return token
        return os.environ.get("EIGENCAPITAL_API_TOKEN", "")

    def get_generic_secret(self, path: str, mount_point: str | None = None) -> dict[str, Any] | None:
        """Read any secret from Vault KV v2.

        Unlike get_mt5_credentials, this method does NOT mutate instance
        config state.  Path and mount_point are passed directly to the
        Vault read call.  Cache keys are path-specific, so concurrent
        calls to different paths do not collide.

        Useful for reading non-MT5 secrets (SLACK_WEBHOOK_URL, etc.).
        Returns the data dict or None if unavailable.
        """
        mp = mount_point or self._config.mount_point
        return self._read_secret(path=path, mount_point=mp)

    def invalidate_cache(self) -> None:
        """Clear the in-memory cache. Test-harness use only."""
        with self._cache_lock:
            self._cache.clear()

    @property
    def is_vault_available(self) -> bool:
        """Check if Vault is configured and reachable."""
        if not self._config.enabled:
            return False
        client = self._ensure_client()
        if client is None:
            return False
        try:
            return bool(client.is_authenticated())
        except (ConnectionError, TimeoutError, OSError, KeyError):
            return False


# ── Module-level singleton ──────────────────────────────────────────────

_default_provider: VaultSecretsProvider | None = None
_default_provider_lock = threading.Lock()


def get_vault_provider(config: VaultConfig | None = None) -> VaultSecretsProvider:
    """Return the global VaultSecretsProvider singleton.

    In tests, pass an explicit ``config`` to create an isolated instance
    without modifying the global singleton.
    """
    global _default_provider
    if config is not None:
        return VaultSecretsProvider(config)
    with _default_provider_lock:
        if _default_provider is None:
            _default_provider = VaultSecretsProvider()
        return _default_provider


def resolve_mt5_credentials(config_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """One-shot MT5 credential resolution for use in config loading.

    ``config_data`` is the raw ``mt5`` dict from YAML (for default values).
    Returns a dict with keys ``account``, ``password``, ``server``, each
    resolved from Vault → env var → YAML default.

    This is the primary integration point with ``MT5Config.from_dict()``.
    """
    provider = get_vault_provider()
    result = provider.get_mt5_credentials()

    # Fill any gaps from YAML defaults
    if config_data:
        result.setdefault("account", int(config_data.get("account", 0)))
        result.setdefault("password", config_data.get("password", ""))
        result.setdefault("server", config_data.get("server", ""))

    return result


def clear_default_provider() -> None:
    """Reset the global singleton. Test-harness use only."""
    global _default_provider
    with _default_provider_lock:
        _default_provider = None
