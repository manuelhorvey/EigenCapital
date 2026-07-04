"""Tests for state persistence integrity (checksums, atomic writes)."""
import hashlib
import json
import os
import tempfile

from paper_trading.state import atomic_write_json


def test_atomic_write_json_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "state.json")
        data = {"key": "value", "num": 42}
        atomic_write_json(path, data)
        assert os.path.exists(path)
        assert not os.path.exists(path + ".tmp")


def test_atomic_write_json_embeds_checksum():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "state.json")
        data = {"key": "value"}
        atomic_write_json(path, data)
        with open(path) as f:
            saved = json.load(f)
        assert "_checksum" in saved
        assert len(saved["_checksum"]) == 64


def test_checksum_verifies_on_read():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "state.json")
        data = {"key": "value"}
        atomic_write_json(path, data)
        with open(path) as f:
            saved = json.load(f)

        stored_cs = saved.pop("_checksum")
        computed = hashlib.sha256(json.dumps(saved, sort_keys=True, default=str).encode()).hexdigest()
        assert computed == stored_cs


def test_checksum_detects_tamper():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "state.json")
        data = {"key": "value"}
        atomic_write_json(path, data)

        with open(path) as f:
            saved = json.load(f)
        saved["key"] = "tampered"
        with open(path, "w") as f:
            json.dump(saved, f)

        with open(path) as f:
            loaded = json.load(f)
        stored_cs = loaded.pop("_checksum", None)
        computed = hashlib.sha256(json.dumps(loaded, sort_keys=True, default=str).encode()).hexdigest()
        assert computed != stored_cs
