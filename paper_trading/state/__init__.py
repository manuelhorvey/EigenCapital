"""State persistence sub-package — focused stores for DB, snapshots, analytics, and cache."""

import hashlib
import json
import math
import os
from dataclasses import dataclass

import numpy as np

from eigencapital.domain.encoding import EigenCapitalJSONEncoder

SCHEMA_VERSION = "1.0.0"
DB_SCHEMA_VERSION = "2.0.0"
CONTRACT_VERSION = 2


@dataclass
class EngineSnapshot:
    schema_version: str = SCHEMA_VERSION
    contract_version: int = CONTRACT_VERSION
    sequence_id: int = 0
    timestamp: str = ""
    portfolio: dict | None = None
    assets: dict | None = None
    open_positions: dict | None = None
    engine_status: dict | None = None
    halt_conditions: dict | None = None
    risk_signals: dict | None = None
    shadow_actions: dict | None = None
    risk_parity: dict | None = None
    emergency_halt: bool = False
    halt_reason: str = ""
    halt_detail: str = ""
    peak_portfolio_value: float | None = None
    peak_capital_base: float | None = None
    breaker_daily_pnl: list[float] | None = None
    mt5: dict | None = None
    asset_values: dict[str, float] | None = None
    risk_state: dict | None = None
    performance_state: dict | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "EngineSnapshot":
        return cls(
            schema_version=d.get("schema_version", "0.0.0"),
            contract_version=d.get("contract_version", 0),
            sequence_id=d.get("sequence_id", 0),
            timestamp=d.get("timestamp", ""),
            portfolio=d.get("portfolio"),
            assets=d.get("assets"),
            open_positions=d.get("open_positions"),
            engine_status=d.get("engine_status"),
            halt_conditions=d.get("halt_conditions"),
            risk_signals=d.get("risk_signals"),
            shadow_actions=d.get("shadow_actions"),
            risk_parity=d.get("risk_parity"),
            emergency_halt=d.get("emergency_halt", False),
            halt_reason=d.get("halt_reason", ""),
            halt_detail=d.get("halt_detail", ""),
            peak_portfolio_value=d.get("peak_portfolio_value"),
            peak_capital_base=d.get("peak_capital_base"),
            breaker_daily_pnl=d.get("breaker_daily_pnl"),
            mt5=d.get("mt5"),
            asset_values=d.get("asset_values"),
            risk_state=d.get("risk_state"),
        )


def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    elif isinstance(obj, (float, np.floating)):
        try:
            if math.isinf(obj) or math.isnan(obj):
                return None
        except TypeError:
            pass
        return obj
    return obj


def atomic_write_json(path: str, data: dict) -> None:
    """Atomic JSON write with embedded SHA256 checksum."""
    checksum = hashlib.sha256(json.dumps(data, sort_keys=True, cls=EigenCapitalJSONEncoder).encode()).hexdigest()
    write_data = {**data, "_checksum": checksum}
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(write_data, f, indent=2, cls=EigenCapitalJSONEncoder)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except (OSError, TypeError, ValueError) as _ae:
        logger.error("atomic_write_json failed: %s", _ae, exc_info=True)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


from paper_trading.state.analytics_store import _AnalyticsStore  # noqa: E402
from paper_trading.state.data_cache import _DataCache  # noqa: E402
from paper_trading.state.database_store import _DatabaseStore  # noqa: E402
from paper_trading.state.snapshot_manager import _SnapshotManager  # noqa: E402

__all__ = [
    "SCHEMA_VERSION",
    "DB_SCHEMA_VERSION",
    "CONTRACT_VERSION",
    "EngineSnapshot",
    "sanitize",
    "atomic_write_json",
    "_DatabaseStore",
    "_SnapshotManager",
    "_AnalyticsStore",
    "_DataCache",
]
