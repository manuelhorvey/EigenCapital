"""Provenance Hashing — deterministic research identity.

Computes a SHA-256 hash of all inputs that produced a research result.
This is the foundation of reproducibility.

Usage:
    h = compute_provenance_hash({
        "git_commit": "a1b2c3d",
        "dataset_hash": "...",
        "strategy_config_hash": "...",
        "parameters": {"lookback": 100},
        "cost_model_id": "realistic_v1",
    })
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def canonical_json_dumps(data: Any) -> str:
    """Produce deterministic JSON string.

    Rules:
    - Sorted keys at every level
    - UTF-8 encoding
    - Explicit null handling
    - No NaN/inf (rejected)
    """
    def _sort(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _sort(v) for k, v in sorted(obj.items())}
        elif isinstance(obj, list):
            return [_sort(item) for item in obj]
        return obj

    sorted_data = _sort(data)
    return json.dumps(
        sorted_data,
        sort_keys=False,  # Already sorted
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def compute_provenance_hash(inputs: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of research inputs.

    Args:
        inputs: Dict of all inputs that produced a result
                (git_commit, dataset, strategy, parameters, costs, etc.)

    Returns:
        64-character hex SHA-256 hash
    """
    canonical = canonical_json_dumps(inputs)
    payload = canonical.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_provenance(inputs: Dict[str, Any], expected_hash: str) -> bool:
    """Verify that inputs match an expected provenance hash."""
    return compute_provenance_hash(inputs) == expected_hash
