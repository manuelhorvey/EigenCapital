"""Custom JSON encoder — handles datetime, date, Decimal, and numpy types.

Usage::

    import json
    from eigencapital.domain.encoding import EigenCapitalJSONEncoder

    data = json.dumps(obj, cls=EigenCapitalJSONEncoder)
    # or
    data = eigencapital_json_dumps(obj)

This encoder replaces ad-hoc ``default=str`` patterns spread across the
codebase with a single, predictable encoder that:

- Serializes ``datetime.datetime`` / ``datetime.date`` → ISO-8601 strings
- Serializes ``decimal.Decimal`` → ``float`` (precision loss is acceptable
  for diagnostics/logging paths; use ``str()`` for audit-grade precision)
- Serializes numpy scalar types (``np.integer``, ``np.floating``,
  ``np.bool_``) → native Python types
- Serializes ``np.ndarray`` → ``list`` via ``.tolist()``
- Falls back to ``str(o)`` for any remaining non-serializable types
  (graceful degradation — this is a diagnostic/logging encoder)
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

__all__ = ["EigenCapitalJSONEncoder", "eigencapital_json_dumps"]

# Sentinel for lazy numpy import — avoids re-checking import machinery
# on every default() call.
_numpy_module: Any | None = None


def _get_numpy():
    """Lazy import numpy — returns the numpy module or None.

    Cached after first import so subsequent calls are fast dict lookups
    in sys.modules rather than re-probing the import machinery.
    """
    global _numpy_module
    if _numpy_module is None:
        try:
            import numpy as _numpy_module  # type: ignore[no-redef]
        except ImportError:
            _numpy_module = False  # sentinel: numpy not available
    return _numpy_module if _numpy_module is not False else None


class EigenCapitalJSONEncoder(json.JSONEncoder):
    """JSON encoder for EigenCapital's cross-cutting serialization needs.

    Known type handling:

    - ``datetime.datetime`` / ``datetime.date`` → ISO-8601 via ``.isoformat()``
    - ``decimal.Decimal`` → ``float``  (sufficient for metrics/diagnostics)
    - numpy integer types (``np.int8`` … ``np.uint64``) → ``int``
    - numpy float types (``np.float16`` … ``np.float128``) → ``float``
    - ``np.bool_`` → ``bool``
    - ``np.ndarray`` → ``list``
    - Everything else → ``str(o)`` (graceful fallback — never crashes)
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)

        np = _get_numpy()
        if np is not None:
            if isinstance(o, np.integer):
                return int(o)
            if isinstance(o, np.floating):
                return float(o)
            if isinstance(o, np.bool_):
                return bool(o)
            if isinstance(o, np.ndarray):
                return o.tolist()

        # Graceful fallback: stringify anything else rather than crash.
        # This keeps engine cycles alive when a diagnostic/logging path
        # encounters an unexpected non-serializable type.
        return str(o)


def eigencapital_json_dumps(obj: Any, **kwargs: Any) -> str:
    """Shorthand for ``json.dumps(obj, cls=EigenCapitalJSONEncoder, **kwargs)``.

    The encoder already falls back to ``str(o)`` for unknown types, so
    passing ``default=str`` is unnecessary.
    """
    kwargs.setdefault("cls", EigenCapitalJSONEncoder)
    return json.dumps(obj, **kwargs)
