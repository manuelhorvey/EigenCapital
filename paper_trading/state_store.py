import fcntl
import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

logger = logging.getLogger("quantforge.state_store")

ET = pytz.timezone("US/Eastern")

SCHEMA_VERSION = "1.0.0"


@dataclass
class EngineSnapshot:
    schema_version: str = SCHEMA_VERSION
    timestamp: str = ""
    portfolio: dict | None = None
    assets: dict | None = None
    open_positions: dict | None = None
    engine_status: dict | None = None
    halt_conditions: dict | None = None
    risk_signals: dict | None = None
    shadow_actions: dict | None = None
    risk_parity: dict | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "EngineSnapshot":
        return cls(
            schema_version=d.get("schema_version", "0.0.0"),
            timestamp=d.get("timestamp", ""),
            portfolio=d.get("portfolio"),
            assets=d.get("assets"),
            open_positions=d.get("open_positions"),
            engine_status=d.get("engine_status"),
            halt_conditions=d.get("halt_conditions"),
            risk_signals=d.get("risk_signals"),
            shadow_actions=d.get("shadow_actions"),
            risk_parity=d.get("risk_parity"),
        )


_SKIP_JOURNAL = object()


def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(v) for v in obj]
    elif isinstance(obj, (float, np.floating)) and (math.isinf(obj) or math.isnan(obj)):
        return None
    return obj


class StateStore:
    def __init__(self, base_dir: str, snapshot_cache_ttl: float = 1.0):
        self.base_dir = base_dir
        self.live_dir = os.path.join(base_dir, "data", "live")
        self.state_path = os.path.join(self.live_dir, "state.json")
        self.trade_journal_path = os.path.join(self.live_dir, "trade_journal.parquet")
        self.confidence_bucket_path = os.path.join(self.live_dir, "confidence_buckets.parquet")
        self.equity_history_path = os.path.join(self.live_dir, "equity_history.json")
        self.review_log_path = os.path.join(self.live_dir, "review_log.json")
        self.trade_outcomes_path = os.path.join(self.live_dir, "trade_outcomes.json")
        self.cache_dir = os.path.join(self.live_dir, "cache")
        self._snapshot_cache = None
        self._snapshot_cache_ttl = snapshot_cache_ttl
        self._analytics_snapshot_counter = 0
        self._analytics_snapshot_frequency = 5  # recompute every N calls
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.live_dir, exist_ok=True)

    def save_snapshot(self, snapshot: EngineSnapshot) -> None:
        self._snapshot_cache = (snapshot, time.monotonic())
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        tmp_path = self.state_path + ".tmp"
        data = sanitize(asdict(snapshot))
        with open(tmp_path, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, indent=2, default=str)
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp_path, self.state_path)

    def load_snapshot(self) -> EngineSnapshot | None:
        if self._snapshot_cache is not None:
            cached, expiry = self._snapshot_cache
            if time.monotonic() < expiry:
                return cached
            self._snapshot_cache = None
        if not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            snapshot = EngineSnapshot.from_dict(data)
            self._snapshot_cache = (snapshot, time.monotonic() + self._snapshot_cache_ttl)
            return snapshot
        except Exception as e:
            logger.warning("Failed to load state snapshot: %s", e)
            return None

    def append_trade(self, trade: dict) -> None:
        df = pd.DataFrame([trade])
        if os.path.exists(self.trade_journal_path):
            existing = pd.read_parquet(self.trade_journal_path)
            for col in ("entry_date", "exit_date"):
                if col in existing.columns:
                    existing[col] = existing[col].astype(str)
                if col in df.columns:
                    df[col] = df[col].astype(str)
            df = pd.concat([existing, df], ignore_index=True)
        df.to_parquet(self.trade_journal_path)

    def read_trades(self, limit: int = 10) -> list:
        try:
            if os.path.exists(self.trade_journal_path):
                df = pd.read_parquet(self.trade_journal_path)
                if len(df) > 0:
                    df = df.sort_values("exit_date", ascending=False).head(limit)
                    return json.loads(df.to_json(orient="records", default_handler=str))
        except Exception:
            pass
        return []

    def read_trades_since(self, date: str) -> pd.DataFrame:
        columns = ["asset", "side", "entry", "exit", "return", "bars", "reason", "entry_date", "exit_date"]
        if not os.path.exists(self.trade_journal_path):
            return pd.DataFrame(columns=columns)
        try:
            df = pd.read_parquet(self.trade_journal_path)
            if df.empty:
                return pd.DataFrame(columns=columns)
            missing = [c for c in columns if c not in df.columns]
            if missing:
                for c in missing:
                    df[c] = None
            return df[df["exit_date"] >= date].copy()
        except Exception:
            return pd.DataFrame(columns=columns)

    def read_trade_outcomes(self) -> dict | None:
        if not os.path.exists(self.trade_outcomes_path):
            return None
        try:
            with open(self.trade_outcomes_path) as f:
                return json.load(f)
        except Exception:
            return None

    def write_trade_outcomes_cache(self) -> None:
        if not os.path.exists(self.trade_journal_path):
            return
        try:
            df = pd.read_parquet(self.trade_journal_path)
            if df.empty:
                return

            reason_col = "reason" if "reason" in df.columns else "exit_reason"
            ret_col = "return" if "return" in df.columns else "pnl"
            r_col = "realized_r" if "realized_r" in df.columns else None

            df[reason_col] = (
                df[reason_col]
                .astype(str)
                .str.lower()
                .replace(
                    {
                        "sl_hit": "sl",
                        "tp_hit": "tp",
                        "gate_closed": "signal_flip",
                    }
                )
            )
            df[ret_col] = pd.to_numeric(df[ret_col], errors="coerce").fillna(0.0)

            by_asset = []
            for asset_name, group in df.groupby("asset"):
                n = len(group)
                tp = (group[reason_col] == "tp").sum()
                sl = (group[reason_col] == "sl").sum()
                flip = (group[reason_col] == "signal_flip").sum()
                wins = (group[ret_col] > 0).sum()
                total_profit = group[ret_col].clip(lower=0).sum()
                total_loss = (-group[ret_col].clip(upper=0)).sum()
                avg_r = float(group[r_col].mean()) if r_col and r_col in group else 0.0

                by_asset.append(
                    {
                        "asset": asset_name,
                        "n_trades": int(n),
                        "tp_rate": round(float(tp) / n, 4) if n > 0 else 0.0,
                        "sl_rate": round(float(sl) / n, 4) if n > 0 else 0.0,
                        "signal_flip_rate": round(float(flip) / n, 4) if n > 0 else 0.0,
                        "avg_r": round(avg_r, 4),
                        "win_rate": round(float(wins) / n, 4) if n > 0 else 0.0,
                        "profit_factor": round(float(total_profit / total_loss), 4) if total_loss > 0 else None,
                    }
                )

            n_total = len(df)
            tp_total = int((df[reason_col] == "tp").sum())
            sl_total = int((df[reason_col] == "sl").sum())
            flip_total = int((df[reason_col] == "signal_flip").sum())
            wins_total = int((df[ret_col] > 0).sum())
            profit_total = float(df[ret_col].clip(lower=0).sum())
            loss_total = float((-df[ret_col].clip(upper=0)).sum())
            avg_r_total = float(df[r_col].mean()) if r_col and r_col in df.columns else 0.0

            payload = {
                "overall": {
                    "tp_rate": round(tp_total / n_total, 4) if n_total > 0 else 0.0,
                    "sl_rate": round(sl_total / n_total, 4) if n_total > 0 else 0.0,
                    "signal_flip_rate": round(flip_total / n_total, 4) if n_total > 0 else 0.0,
                    "avg_r": round(avg_r_total, 4),
                    "win_rate": round(wins_total / n_total, 4) if n_total > 0 else 0.0,
                    "profit_factor": round(profit_total / loss_total, 4) if loss_total > 0 else None,
                },
                "by_asset": by_asset,
                "updated_at": datetime.now(tz=ET).isoformat(),
            }

            with open(self.trade_outcomes_path, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logger.warning("Failed to write trade outcomes cache: %s", e)

    def append_attribution(self, record_dict: dict) -> None:
        """Persist a single TradeAttributionRecord flattened dict to attribution.parquet.

        Centralized store for dashboard consumption. Does NOT replace per-asset
        experiment export — this is the durable queryable copy.
        """
        path = os.path.join(self.live_dir, "attribution.parquet")
        df = pd.DataFrame([record_dict])
        for col in ("entry_date", "exit_date", "created_at"):
            if col in df.columns:
                df[col] = df[col].astype(str)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                existing = pd.read_parquet(path)
                for col in ("entry_date", "exit_date", "created_at"):
                    if col in existing.columns:
                        existing[col] = existing[col].astype(str)
                df = pd.concat([existing, df], ignore_index=True)
            except Exception:
                pass
        df.to_parquet(path, index=False)

    def read_attribution(self, limit: int = 100, offset: int = 0,
                         archetype: str | None = None,
                         regime: str | None = None,
                         asset: str | None = None) -> list:
        """Read attribution records with optional filters."""
        path = os.path.join(self.live_dir, "attribution.parquet")
        if not os.path.exists(path):
            return []
        try:
            df = pd.read_parquet(path)
            if archetype:
                df = df[df.get("pred_archetype_at_entry", "") == archetype]
            if regime:
                df = df[df.get("pred_regime_at_entry", "") == regime]
            if asset:
                df = df[df.get("asset", "") == asset]
            df = df.sort_values("exit_date", ascending=False).iloc[offset:offset + limit]
            return json.loads(df.to_json(orient="records", default_handler=str))
        except Exception as e:
            logger.warning("Failed to read attribution: %s", e)
            return []

    def append_shadow_trade(self, record_dict: dict) -> None:
        """Persist a single ShadowTradeRecord dict to shadow_trades.parquet."""
        path = os.path.join(self.live_dir, "shadow_trades.parquet")
        df = pd.DataFrame([record_dict])
        for col in ("entry_date", "exit_date"):
            if col in df.columns:
                df[col] = df[col].astype(str)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                existing = pd.read_parquet(path)
                for col in ("entry_date", "exit_date"):
                    if col in existing.columns:
                        existing[col] = existing[col].astype(str)
                df = pd.concat([existing, df], ignore_index=True)
            except Exception:
                pass
        df.to_parquet(path, index=False)

    def read_shadow_trades(self, limit: int = 100, offset: int = 0,
                           alt_label: str | None = None) -> list:
        """Read shadow trade records with optional filter."""
        path = os.path.join(self.live_dir, "shadow_trades.parquet")
        if not os.path.exists(path):
            return []
        try:
            df = pd.read_parquet(path)
            if alt_label:
                df = df[df.get("alt_label", "") == alt_label]
            df = df.sort_values("exit_date", ascending=False).iloc[offset:offset + limit]
            return json.loads(df.to_json(orient="records", default_handler=str))
        except Exception as e:
            logger.warning("Failed to read shadow trades: %s", e)
            return []

    def write_analytics_snapshot(self) -> None:
        """Precompute analytics aggregates and cache to analytics_snapshot.json.

        Called periodically from the engine main loop (not from API routes).
        Uses a frequency gate (_analytics_snapshot_frequency) to avoid
        recomputing on every call. Routes should prefer this cache over
        live parquet reads for expensive aggregations.
        """
        self._analytics_snapshot_counter += 1
        if self._analytics_snapshot_counter < self._analytics_snapshot_frequency:
            return
        self._analytics_snapshot_counter = 0
        attrs = self.read_attribution(limit=2000)
        shadows = self.read_shadow_trades(limit=2000)
        snapshot: dict = {}

        if attrs:
            import pandas as pd
            df = pd.DataFrame(attrs)
            arch_col = "pred_archetype_at_entry"
            regime_col = "pred_regime_at_entry"
            reason_col = "exit_exit_reason"

            # Overall
            r_values = df.get("exit_realized_r", df.get("realized_r", 0))
            snapshot["overall"] = {
                "n_trades": len(df),
                "avg_r": float(r_values.mean()),
                "win_rate": float((r_values > 0).mean()),
                "tp_rate": float((df.get(reason_col, "") == "tp").mean()),
                "sl_rate": float((df.get(reason_col, "") == "sl").mean()),
            }

            # Per archetype
            by_arch = {}
            if arch_col in df.columns:
                for arch, grp in df.groupby(arch_col):
                    grp_r = grp.get("exit_realized_r", 0)
                    by_arch[arch] = {
                        "n": len(grp),
                        "avg_r": float(grp_r.mean()),
                        "win_rate": float((grp_r > 0).mean()),
                        "tp_rate": float((grp.get(reason_col, "") == "tp").mean()),
                        "sl_rate": float((grp.get(reason_col, "") == "sl").mean()),
                        "avg_entry_slippage": float(grp.get("friction_entry_slippage_bps", 0).mean()),
                        "avg_mae": float(grp.get("exit_mae", 0).mean()),
                        "avg_mfe": float(grp.get("exit_mfe", 0).mean()),
                    }
            snapshot["by_archetype"] = by_arch

            # Per regime
            by_reg = {}
            if regime_col in df.columns:
                for reg, grp in df.groupby(regime_col):
                    grp_r = grp.get("exit_realized_r", 0)
                    by_reg[reg] = {
                        "n": len(grp),
                        "avg_r": float(grp_r.mean()),
                        "win_rate": float((grp_r > 0).mean()),
                    }
            snapshot["by_regime"] = by_reg

        if shadows:
            import pandas as pd
            sdf = pd.DataFrame(shadows)
            n = len(sdf)
            same = (sdf.get("exit_reason", "") == sdf.get("live_exit_reason", "")).sum()
            shadow_divergence_rate = 1 - (same / n) if n > 0 else 0
            r_delta = sdf.get("realized_r", 0) - sdf.get("live_realized_r", 0)
            snapshot["shadow"] = {
                "n": n,
                "divergence_rate": round(shadow_divergence_rate, 4),
                "avg_r_delta": round(float(r_delta.mean()), 4),
            }

        snapshot["updated_at"] = datetime.now(tz=ET).isoformat()

        try:
            path = os.path.join(self.live_dir, "analytics_snapshot.json")
            with open(path, "w") as f:
                json.dump(snapshot, f, indent=2, default=str)
        except Exception as e:
            logger.warning("Failed to write analytics snapshot: %s", e)

    def read_analytics_snapshot(self) -> dict | None:
        """Read the precomputed analytics snapshot if available."""
        path = os.path.join(self.live_dir, "analytics_snapshot.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None

    def append_confidence_bucket(self, bucket: dict) -> None:
        df = pd.DataFrame([bucket])
        if os.path.exists(self.confidence_bucket_path) and os.path.getsize(self.confidence_bucket_path) > 0:
            try:
                existing = pd.read_parquet(self.confidence_bucket_path)
                df = pd.concat([existing, df], ignore_index=True)
            except Exception:
                pass
        df.to_parquet(self.confidence_bucket_path)

    def append_equity_history(self, record: dict) -> None:
        os.makedirs(os.path.dirname(self.equity_history_path), exist_ok=True)
        history = []
        if os.path.exists(self.equity_history_path):
            try:
                with open(self.equity_history_path) as f:
                    history = json.load(f)
            except (json.JSONDecodeError, ValueError):
                history = []
        history.append(record)
        history = sanitize(history[-2000:])
        with open(self.equity_history_path, "w") as f:
            json.dump(history, f, indent=2, allow_nan=False)

    def read_equity_history(self) -> list:
        if not os.path.exists(self.equity_history_path):
            return []
        try:
            with open(self.equity_history_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []

    def cache_path(self, ticker: str) -> str:
        safe_name = ticker.replace("=", "_").replace("-", "_")
        return os.path.join(self.cache_dir, f"{safe_name}.parquet")

    def save_cache(self, ticker: str, df: pd.DataFrame) -> None:
        path = self.cache_path(ticker)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_parquet(path)

    def load_cache(self, ticker: str) -> pd.DataFrame | None:
        path = self.cache_path(ticker)
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    return df
            except Exception as e:
                logger.warning("Cache read error for %s: %s", ticker, e)
        return None
