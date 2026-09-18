"""Trade Stream Persistence — deterministic JSON round-trip with verification.

R1 Phase A (docs/research/R0_INFRASTRUCTURE_VERIFICATION.md, PATCH item).

Format: a single UTF-8 JSON object (``TradeStream.to_dict()``) written with
canonical JSON rules (sorted keys at every level, no NaN/inf) so byte-identical
streams produce byte-identical files. Every load re-verifies the provenance
hash over the loaded content, so tampering (any value edit, trade insertion,
removal or reordering) is detected at read time.

The format is deliberately boring: one file, one stream, no compression, no
external dependency — the same persistence posture as the rest of EigenCapital
research evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from eigencapital.core.provenance import canonical_json_dumps
from eigencapital.research.monte_carlo.schema import (
    TradeStream,
    TradeStreamError,
)

PathLike = str | Path


def save_trade_stream(stream: TradeStream, path: PathLike) -> Path:
    """Persist a trade stream as canonical JSON.

    Args:
        stream: The stream to persist. Its provenance hash is re-verified
            against the content before writing (defence in depth).
        path: Destination file path (parent directories created as needed).

    Returns:
        The resolved path written.

    Raises:
        TradeStreamError: If the stream's stored hash does not match its
            content, or the content cannot be serialized.
    """
    if not stream.verify_provenance_hash(stream.provenance_hash):
        raise TradeStreamError(
            f"refusing to save: stored provenance_hash does not match content (stream {stream.stream_id})",
            stream_id=stream.stream_id,
        )
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_dumps(stream.to_dict())
    destination.write_text(payload, encoding="utf-8")
    return destination


def load_trade_stream(path: PathLike) -> TradeStream:
    """Load a trade stream and verify its provenance hash over the content.

    Args:
        path: Source file path.

    Returns:
        The verified TradeStream. The provenance hash stored in the file is
        compared against a hash recomputed from the loaded trades and identity
        fields; any mismatch raises.

    Raises:
        TradeStreamError: On malformed JSON, schema violations, or provenance
            hash mismatch (tamper detection).
    """
    source = Path(path)
    if not source.is_file():
        raise TradeStreamError(f"trade stream file not found: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise TradeStreamError(f"unreadable trade stream file {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise TradeStreamError(f"trade stream file must contain a JSON object: {source}")
    try:
        stream = TradeStream.from_dict(data)
    except TradeStreamError:
        raise
    except (TypeError, KeyError, ValueError) as exc:
        raise TradeStreamError(f"invalid trade stream content in {source}: {exc}") from exc
    if not stream.verify_provenance_hash(stream.provenance_hash):
        raise TradeStreamError(
            f"provenance hash mismatch in {source}: file content does not match stored hash "
            f"(stream {stream.stream_id})",
            stream_id=stream.stream_id,
        )
    return stream
