"""Canonical serialization for EigenCapital provenance and hashing.

Correction #9 from architecture review:
    canonical serialization:
    - sorted keys
    - UTF-8
    - explicit null handling
    - ISO-8601 UTC timestamps
    - stable enum representation
    - normalized floating-point representation
    - no unordered dict dependence

Every domain model's to_dict() should produce a dict that, when passed
through canonical_sort(), produces a deterministic representation suitable
for hashing.

Usage:
    from eigencapital.core.models.canonical_serialization import (
        canonical_sort,
        canonical_json,
        canonical_hash,
    )

    data = some_model.to_dict()
    canonical = canonical_sort(data)
    h = canonical_hash(data)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List


def canonical_sort(data: Any) -> Any:
    """Recursively sort dict keys alphabetically for deterministic output.

    Rules:
    1. Dict keys sorted alphabetically at every level (recursively)
    2. Lists are kept in order (caller must sort before serialization if order matters)
    3. Null/None values are preserved explicitly (not omitted)
    4. Primitive values pass through unchanged

    Args:
        data: Any JSON-serializable value

    Returns:
        Same structure with all dict keys sorted recursively
    """
    if isinstance(data, dict):
        return {k: canonical_sort(v) for k, v in sorted(data.items())}
    elif isinstance(data, list):
        return [canonical_sort(item) for item in data]
    else:
        return data


def canonical_json(data: Any, indent: int | None = None) -> str:
    """Produce deterministic JSON string from a domain model dict.

    Serialization contract:
    1. Keys sorted alphabetically at every level
    2. UTF-8 encoding
    3. Explicit null handling: None values included as null, not omitted
    4. ISO-8601 UTC timestamps: strings preserved as-is (caller ensures format)
    5. Stable enum representation: enum name as string, not integer
    6. Normalized floating-point: Python float representation
    7. No unordered dict dependence
    8. Separators: (',', ': ') for human readability in logs

    Args:
        data: Dict from a domain model's to_dict()
        indent: Optional indentation for pretty-printing

    Returns:
        Deterministic JSON string
    """
    sorted_data = canonical_sort(data)
    return json.dumps(
        sorted_data,
        sort_keys=False,  # Already sorted by canonical_sort
        ensure_ascii=False,  # UTF-8
        allow_nan=False,  # Reject NaN/inf — should be caught by domain validation
        indent=indent,
        separators=(",", ": ") if indent is None else None,
    )


def canonical_hash(data: Any, algorithm: str = "sha256") -> str:
    """Produce deterministic hash of a domain model dict.

    Args:
        data: Dict from a domain model's to_dict()
        algorithm: Hash algorithm (default: sha256)

    Returns:
        Hex-encoded hash string
    """
    canonical = canonical_json(data)
    payload = canonical.encode("utf-8")
    return hashlib.new(algorithm, payload).hexdigest()


def canonical_hash_hex(data: Any) -> str:
    """Alias for canonical_hash with sha256 (64-char hex string)."""
    return canonical_hash(data, algorithm="sha256")
