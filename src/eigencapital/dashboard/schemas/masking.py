"""DTO-layer masking for the dashboard's broad streaming surface (M-8).

FINDINGS.md M-8 (human decision): mask in the DTO layer — account IDs masked
(keep at most the last four characters), balances/P&L/notionals rounded, names
truncated; exact values stay available only behind the authenticated `/api/v1`
API (`X-API-Key` / `Authorization: Bearer`, H-11).

Where it applies: the live stream (`/ws/live` broadcast and
`/api/v1/events/stream`) is the broadly shared surface — ONE snapshot from
`streaming.events.get_live_state()` fans out to every connected viewer, so it
is passed through `mask_live_state()` before serialisation. The authenticated
REST endpoints the dashboard itself queries keep exact values for legitimate
use and never call this module.

Precision: amounts are rounded to three significant figures — the same
precision as the `$12.4K` abbreviation cited in the finding — so the masked
value stays renderable by the client's `formatCurrency` (two decimals)
without revealing the exact figure. Ratios (`*_pct`, `*_utilization`,
concentration) are not money and are left untouched; so are counts, tickets,
symbols and timestamps.
"""

from __future__ import annotations

import math
from typing import Any

# Account IDs keep at most the last four characters; the prefix is masked.
ACCOUNT_ID_TAIL = 4

# Amounts are rounded to this many significant figures ($12.4K-class precision).
AMOUNT_SIGNIFICANT_DIGITS = 3

# Names / free-text labels longer than this many characters are truncated.
NAME_MAX_LENGTH = 32

# ASCII-safe escapes keep this module pure-ASCII source.
MASK_CHAR = "\u2022"
TRUNCATION_CHAR = "\u2026"

# Scalar values under these keys are account identifiers → keep last 4 only.
_ACCOUNT_ID_KEYS = frozenset(
    {
        "account",
        "account_id",
        "account_number",
        "account_login",
        "broker_account",
        "login",
    }
)

# String values under these keys are names / free text → truncated.
_NAME_KEYS = frozenset(
    {
        "name",
        "account_name",
        "title",
        "label",
        "category",
        "description",
        "message",
    }
)

# Numeric values under these keys are balances / P&L / notionals / prices → rounded.
_AMOUNT_KEYS = frozenset(
    {
        "amount",
        "balance",
        "current_price",
        "daily_loss_remaining",
        "daily_pnl",
        "distance_to_sl",
        "drawdown",
        "entry_price",
        "equity",
        "equity_high_water",
        "free_margin",
        "gross_exposure",
        "limit",
        "loss",
        "margin_used",
        "max_capital",
        "max_daily_loss",
        "max_drawdown",
        "max_order_notional",
        "max_position_notional",
        "min_equity",
        "net_exposure",
        "notional",
        "pnl",
        "price_current",
        "price_open",
        "profit",
        "stop_loss",
        "t0_equity",
        "unrealized_pnl",
        "value",
    }
)

_AMOUNT_SUFFIXES = (
    "_balance",
    "_drawdown",
    "_equity",
    "_exposure",
    "_loss",
    "_margin",
    "_notional",
    "_pnl",
    "_price",
)

# Ratios/percentages are never money — never round them as an amount.
_RATIO_SUFFIXES = ("_pct", "_ratio", "_utilization")


def _is_amount_key(key: str) -> bool:
    if key.endswith(_RATIO_SUFFIXES):
        return False
    return key in _AMOUNT_KEYS or key.endswith(_AMOUNT_SUFFIXES)


def mask_account_id(value: Any) -> Any:
    """Mask an account identifier, keeping at most the last four characters."""
    if value is None:
        return None
    text = str(value)
    if len(text) <= ACCOUNT_ID_TAIL:
        return MASK_CHAR * len(text)
    return MASK_CHAR * (len(text) - ACCOUNT_ID_TAIL) + text[-ACCOUNT_ID_TAIL:]


def mask_amount(value: int | float) -> int | float:
    """Round a monetary/notional value to three significant figures.

    Keeps the value numeric (and keeps `int` inputs integral) so the DTO
    contract of the streaming payload is unchanged — only its precision is.
    """
    if isinstance(value, bool):
        return value
    number = float(value)
    if not math.isfinite(number) or number == 0:
        return value
    exponent = math.floor(math.log10(abs(number)))
    decimals = AMOUNT_SIGNIFICANT_DIGITS - 1 - exponent
    rounded = round(number, decimals)
    return int(rounded) if isinstance(value, int) else float(rounded)


def mask_name(value: Any) -> Any:
    """Truncate a name / free-text label beyond NAME_MAX_LENGTH characters."""
    if not isinstance(value, str) or len(value) <= NAME_MAX_LENGTH:
        return value
    return value[:NAME_MAX_LENGTH] + TRUNCATION_CHAR


def _mask_entry(key: str, value: Any) -> Any:
    """Mask one key/value pair, recursing into nested dicts and lists."""
    if isinstance(value, dict):
        return {child_key: _mask_entry(child_key, child) for child_key, child in value.items()}
    if isinstance(value, list):
        # Lists keep their parent key so a list of amounts under one name is
        # still masked; list items that are dicts mask by their own keys.
        return [_mask_entry(key, item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if key in _ACCOUNT_ID_KEYS and isinstance(value, (str, int)):
        return mask_account_id(value)
    if key in _NAME_KEYS and isinstance(value, str):
        return mask_name(value)
    if _is_amount_key(key) and isinstance(value, (int, float)):
        return mask_amount(value)
    return value


def mask_dto(payload: Any) -> Any:
    """Recursively mask an arbitrary DTO payload (M-8)."""
    return _mask_entry("", payload)


def mask_live_state(data: dict[str, Any]) -> dict[str, Any]:
    """Mask the live-state DTO payload before it is serialised to the stream.

    Applied by `streaming.events.get_live_state()` — the single builder behind
    both the WebSocket broadcast and the SSE feed. Exact values remain on the
    authenticated REST endpoints.
    """
    return {key: _mask_entry(key, value) for key, value in data.items()}
