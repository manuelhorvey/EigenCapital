"""Tests for model hash loading with corruption detection."""

from __future__ import annotations

import hashlib
import os
import pathlib

import pytest

from paper_trading.asset_engine import AssetEngine


@pytest.fixture
def mock_asset():
    """Create a minimal mock with the contract/model_path attributes used by _load_model_hash."""

    class MockAsset:
        name = "TESTASSET"
        model_path = ""
        _model_hash_verified = True

    return MockAsset()


def _write_model_file(path: str, content: bytes) -> str:
    with open(path, "wb") as f:
        f.write(content)
    return hashlib.sha256(content).hexdigest()[:16]


def _write_sidecar(path: str, hash_val: str) -> None:
    hash_path = path.replace(".json", "_hash.txt")
    with open(hash_path, "w") as f:
        f.write(hash_val)


class TestModelHashLoading:
    def test_matching_sidecar_and_model(self, tmp_path: pathlib.Path) -> None:
        """Returns stored hash and sets verified=True when hashes match."""
        model_path = os.path.join(tmp_path, "TESTASSET_model.json")
        content = b"mock model data"
        expected = _write_model_file(model_path, content)
        _write_sidecar(model_path, expected)

        asset = AssetEngine.__new__(AssetEngine)
        asset.model_path = model_path
        asset.name = "TESTASSET"
        result = asset._load_model_hash()

        assert result == expected
        assert asset._model_hash_verified is True

    def test_corrupted_model_mismatch(self, tmp_path: pathlib.Path) -> None:
        """Returns stored hash and sets verified=False when hashes differ."""
        model_path = os.path.join(tmp_path, "TESTASSET_model.json")
        _write_model_file(model_path, b"original content")
        _write_sidecar(model_path, "deadbeef12345678")

        asset = AssetEngine.__new__(AssetEngine)
        asset.model_path = model_path
        asset.name = "TESTASSET"
        result = asset._load_model_hash()

        assert result == "deadbeef12345678"
        assert asset._model_hash_verified is False

    def test_no_sidecar_computes_from_model(self, tmp_path: pathlib.Path) -> None:
        """Computes hash from model file when sidecar is missing."""
        model_path = os.path.join(tmp_path, "TESTASSET_model.json")
        content = b"no sidecar model data"
        expected = _write_model_file(model_path, content)

        asset = AssetEngine.__new__(AssetEngine)
        asset.model_path = model_path
        asset.name = "TESTASSET"
        result = asset._load_model_hash()

        assert result == expected
        assert asset._model_hash_verified is True

    def test_no_model_file_returns_unknown(self) -> None:
        """Returns 'unknown' when neither model nor sidecar exists."""
        asset = AssetEngine.__new__(AssetEngine)
        asset.model_path = "/tmp/nonexistent_model.json"
        asset.name = "TESTASSET"
        result = asset._load_model_hash()

        assert result == "unknown"
        assert asset._model_hash_verified is True

    def test_sidecar_no_model_file(self, tmp_path: pathlib.Path) -> None:
        """Returns sidecar hash when model file is missing."""
        hash_path = os.path.join(tmp_path, "TESTASSET_model_hash.txt")
        with open(hash_path, "w") as f:
            f.write("abcdef1234567890")

        asset = AssetEngine.__new__(AssetEngine)
        asset.model_path = os.path.join(tmp_path, "TESTASSET_model.json")
        asset.name = "TESTASSET"
        result = asset._load_model_hash()

        assert result == "abcdef1234567890"
        assert asset._model_hash_verified is True

    def test_sidecar_empty_string(self, tmp_path: pathlib.Path) -> None:
        """Handles sidecar with empty string gracefully."""
        model_path = os.path.join(tmp_path, "TESTASSET_model.json")
        content = b"some model data"
        _write_model_file(model_path, content)
        hash_path = model_path.replace(".json", "_hash.txt")
        with open(hash_path, "w") as f:
            f.write("")

        asset = AssetEngine.__new__(AssetEngine)
        asset.model_path = model_path
        asset.name = "TESTASSET"
        result = asset._load_model_hash()

        # Should compute from model file since sidecar is empty
        expected = hashlib.sha256(content).hexdigest()[:16]
        assert result == expected
        assert asset._model_hash_verified is True
