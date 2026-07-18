"""Patching for engine tests — prevents slow network calls in every test."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _patch_macro_fetch():
    with patch("features.data_fetch.prefetch_shared_data", return_value={}):
        yield
