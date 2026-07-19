"""Tests for state persistence integrity (checksums, atomic writes)."""

import hashlib
import json
import tempfile

from eigencapital.domain.encoding import EigenCapitalJSONEncoder
from paper_trading.state import atomic_write_json
from pathlib import Path


def test_atomic_write_json_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state.json"
        data = {"key": "value", "num": 42}
        atomic_write_json(path, data)
        assert Path(path).exists()
        assert not Path(str(path) + ".tmp").exists()


def test_atomic_write_json_embeds_checksum():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state.json"
        data = {"key": "value"}
        atomic_write_json(path, data)
        with open(path) as f:
            saved = json.load(f)
        assert "_checksum" in saved
        assert len(saved["_checksum"]) == 64


def test_checksum_verifies_on_read():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state.json"
        data = {"key": "value"}
        atomic_write_json(path, data)
        with open(path) as f:
            saved = json.load(f)

        stored_cs = saved.pop("_checksum")
        computed = hashlib.sha256(json.dumps(saved, sort_keys=True, cls=EigenCapitalJSONEncoder).encode()).hexdigest()
        assert computed == stored_cs


def test_checksum_detects_tamper():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "state.json"
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
        computed = hashlib.sha256(json.dumps(loaded, sort_keys=True, cls=EigenCapitalJSONEncoder).encode()).hexdigest()
        assert computed != stored_cs
