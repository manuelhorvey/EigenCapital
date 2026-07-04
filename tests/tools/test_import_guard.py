import sys
import types
from unittest.mock import patch

import pytest

from tools.import_guard import (
    FORBIDDEN_MODULES,
    assert_clean_import_graph,
    check_import_firewall,
    verify_feature_pipeline,
)


class TestCheckImportFirewall:
    def test_returns_list_of_strings(self):
        violations = check_import_firewall()
        assert isinstance(violations, list)
        for v in violations:
            assert isinstance(v, str)

    def test_detects_forbidden_module_when_loaded(self):
        sample = next(iter(FORBIDDEN_MODULES))
        with patch.dict(sys.modules, {sample: types.ModuleType(sample)}):
            violations = check_import_firewall()
            assert sample in violations


class TestAssertCleanImportGraph:
    def test_raises_when_forbidden_module_loaded(self):
        sample = next(iter(FORBIDDEN_MODULES))
        with patch.dict(sys.modules, {sample: types.ModuleType(sample)}):
            with pytest.raises(RuntimeError, match="Import firewall violation"):
                assert_clean_import_graph()


class TestVerifyFeaturePipeline:
    def test_returns_status_dict_with_correct_types(self):
        result = verify_feature_pipeline()
        assert "status" in result
        assert result["status"] in ("CLEAN", "VIOLATION")
        assert isinstance(result["allowed_features_loaded"], list)
        assert isinstance(result["forbidden_modules_loaded"], list)

    def test_returns_violation_when_forbidden_loaded(self):
        sample = next(iter(FORBIDDEN_MODULES))
        with patch.dict(sys.modules, {sample: types.ModuleType(sample)}):
            result = verify_feature_pipeline()
            assert result["status"] == "VIOLATION"
            assert sample in result["forbidden_modules_loaded"]
