"""F-21: research-only modules must not be importable outside tests."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO / "src" / "eigencapital" / "research" / "alpha" / "executor.py"
PROBE_NAME = "eigencapital.research.alpha.executor_guard_probe"


def _load_fresh_module(env_value):
    """Load executor.py under a fresh probe name; restore env afterwards."""
    sys.modules.pop(PROBE_NAME, None)
    previous = os.environ.get("EIGENCAPITAL_RESEARCH_ALLOW_IMPORTS")
    if env_value is None:
        os.environ.pop("EIGENCAPITAL_RESEARCH_ALLOW_IMPORTS", None)
    else:
        os.environ["EIGENCAPITAL_RESEARCH_ALLOW_IMPORTS"] = env_value
    try:
        spec = importlib.util.spec_from_file_location(PROBE_NAME, MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            os.environ.pop("EIGENCAPITAL_RESEARCH_ALLOW_IMPORTS", None)
        else:
            os.environ["EIGENCAPITAL_RESEARCH_ALLOW_IMPORTS"] = previous
        sys.modules.pop(PROBE_NAME, None)


def test_executor_raises_without_test_flag():
    """SIMULATED_EVIDENCE must not be importable outside tests."""
    with pytest.raises(RuntimeError, match="research-only"):
        _load_fresh_module(env_value=None)


def test_executor_imports_with_test_flag():
    """With the test flag the module loads and exposes simulated evidence."""
    module = _load_fresh_module(env_value="1")
    assert hasattr(module, "SIMULATED_EVIDENCE")
    assert hasattr(module, "CampaignExecutor")
