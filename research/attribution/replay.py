"""AttributionReplay — offline attribution replay using CounterfactualEngine.

Reads closed-trade data (from lifecycle results or attribution parquet) and
uses the actual DecisionProvenance records (stored in SQLite) to replay the
entry decision through CounterfactualEngine, producing authoritative layer
attribution for each trade.

Two modes:
  provenance  — loads actual DecisionProvenance from SqliteProvenanceStore,
                runs CounterfactualEngine.probability_override() with raw
                probabilities, computes full TradeAttribution.
  trade_only  — fallback when provenance is unavailable; uses the same
                production heuristic (pre-calibration signal capture) that
                the live pipeline already computes.

Usage::

    from research.attribution.replay import AttributionReplay

    replay = AttributionReplay(provenance_db="data/live/provenance.db")
    results = replay.run(trades_source="data/processed/trade_lifecycle_results.json")
    summary = replay.summarize(results)
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from eigencapital.domain.provenance.counterfactual import CounterfactualEngine
from eigencapital.domain.provenance.decision_id import DecisionID
from eigencapital.domain.provenance.decision_provenance import DecisionProvenance
from eigencapital.domain.provenance.decision_trace import DecisionTrace
from eigencapital.domain.provenance.model_context import ModelContext
from eigencapital.domain.provenance.provenance_store import SqliteProvenanceStore

from research.attribution.calculator import TradeAttributionCalculator

logger = logging.getLogger("eigencapital.attribution.replay")

ROOT = Path(__file__).resolve().parent.parent.parent
PROVENANCE_DB_DEFAULT = str(ROOT / "data" / "live" / "provenance.db")
TRADES_DEFAULT = str(ROOT / "data" / "processed" / "trade_lifecycle_results.json")

COUNTERFACTUAL_VERSION_CALIBRATION = "calibration_baseline_v1"


@dataclass
class ReplayResult:
    """Aggregate of all replayed attributions."""

    trades: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    total_realized_r: float = 0.0
    total_attributed_r: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    n_trades: int = 0
    n_with_provenance: int = 0
    n_with_calibration_delta: int = 0
    calibration_delta_r: float = 0.0


class AttributionReplay:
    """Offline attribution replay orchestrator."""

    def __init__(
        self,
        provenance_db: str | None = None,
    ):
        self._provenance_db = provenance_db
        self._prov_store: SqliteProvenanceStore | None = None
        self._cf_engine = CounterfactualEngine()
        self._calculator = TradeAttributionCalculator()

    def _ensure_provenance_store(self) -> SqliteProvenanceStore | None:
        if self._prov_store is not None:
            return self._prov_store
        if self._provenance_db is None:
            return None
        db_path = str(Path(self._provenance_db).expanduser().resolve())
        if not Path(db_path).exists():
            logger.warning("Provenance DB not found at %s", db_path)
            return None
        self._prov_store = SqliteProvenanceStore(db_path)
        self._prov_store.initialize()
        return self._prov_store

    def run(
        self,
        trades_source: str | dict | list = TRADES_DEFAULT,
        *,
        asset_filter: str | None = None,
        limit: int = 0,
    ) -> ReplayResult:
        """Run attribution replay on all loaded trades.

        Args:
            trades_source: Path to JSON file, or pre-loaded dict/list of trades.
            asset_filter: Optional asset name to filter.
            limit: Max trades to process (0 = all).

        Returns:
            ReplayResult with per-trade attributions and summary.
        """
        trades = self._load_trades(trades_source)
        if asset_filter:
            trades = [t for t in trades if t.get("asset", "").upper() == asset_filter.upper()]
        if limit > 0:
            trades = trades[:limit]

        result = ReplayResult()
        result.n_trades = len(trades)

        store = self._ensure_provenance_store()

        for trade in trades:
            attribution = self._replay_one(trade, store)
            result.trades[trade.get("asset", "UNKNOWN")].append(attribution)

            realized = attribution.get("realized_r", 0.0) or 0.0
            result.total_realized_r += realized

            for layer in ("entry", "calibration", "exit", "profit_floor", "portfolio", "risk"):
                alpha = attribution.get(f"{layer}_alpha_r")
                if alpha is not None:
                    result.total_attributed_r[layer] += alpha

            cal_status = attribution.get("calibration_alpha_status")
            if cal_status == "APPLIED":
                cal_alpha = attribution.get("calibration_alpha_r", 0.0) or 0.0
                result.calibration_delta_r += cal_alpha
                if cal_alpha != 0.0:
                    result.n_with_calibration_delta += 1

        return result

    def _load_trades(self, source: str | dict | list) -> list[dict]:
        """Load trades from file or dict."""
        if isinstance(source, (dict, list)):
            data = source
        else:
            path = Path(source)
            if not path.exists():
                logger.warning("Trade file not found at %s", path)
                return []
            with open(path) as f:
                data = json.load(f)

        if isinstance(data, dict):
            trades_dict = data.get("_trades", data)
            if isinstance(trades_dict, dict):
                flat = []
                for asset, tlist in trades_dict.items():
                    for t in tlist:
                        t["asset"] = asset
                        flat.append(t)
                return flat
        if isinstance(data, list):
            return data
        return []

    def _replay_one(self, trade: dict, store: SqliteProvenanceStore | None) -> dict:
        """Replay attribution for a single trade.

        Uses provenance mode when possible, falls back to trade-only mode.
        Returns the TradeAttribution dict.
        """
        realized_r = float(trade.get("realized_r", 0) or trade.get("r_multiple", 0))
        side_str = str(trade.get("side", "long")).lower()
        asset = str(trade.get("asset", "UNKNOWN"))
        entry_price = float(trade.get("entry", 0) or 0)
        sl_price = trade.get("sl_price") or trade.get("stop_loss")
        tp_price = trade.get("tp_price") or trade.get("take_profit")
        mfe = float(trade.get("mfe", 0) or 0)
        conf = float(trade.get("conf_at_entry", 0) or 0)
        bars = int(trade.get("bars", 0) or trade.get("bars_held", 0))
        exit_reason = str(trade.get("reason", "SL") or trade.get("exit_reason", "SL"))
        entry_archetype = str(trade.get("archetype_at_entry", "") or trade.get("entry_archetype", ""))

        # ── Entry attribution: use MFE as first-intervention proxy ─────
        _first_itv_price: float | None = None
        _risk_price: float = 1.0
        if entry_price > 0 and mfe > 0 and sl_price is not None:
            try:
                _sl = float(sl_price)
                if _sl != entry_price:
                    _risk_price = abs(entry_price - _sl)
                    if _risk_price > 0:
                        _first_itv_price = entry_price + mfe if side_str == "long" else entry_price - mfe
            except (TypeError, ValueError):
                pass

        # ── Exit attribution: static TP R-multiple ─────────────────────
        _static_tp_r: float | None = trade.get("counterfactual_fixed_tp_r")
        if _static_tp_r is None and entry_price > 0 and tp_price is not None and sl_price is not None:
            try:
                _sl = float(sl_price)
                _tp = float(tp_price)
                if _sl != entry_price:
                    _risk = abs(entry_price - _sl)
                    if _risk > 0:
                        _tp_ret = (_tp / entry_price - 1) if side_str == "long" else (entry_price / _tp - 1)
                        _static_tp_r = round(_tp_ret / (_risk / entry_price), 4)
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        # ── Calibration attribution ────────────────────────────────────
        _calibrated = conf > 0
        _uncal_signal_r: float | None = None
        _cal_status = "NOT_AVAILABLE"

        # Try provenance mode first
        if store is not None:
            prov = self._find_provenance_for_trade(trade, store)
            if prov is not None:
                _uncal_signal_r, _cal_status = self._compute_calibration_from_provenance(prov, side_str, realized_r)

        # Fallback to trade-only heuristic
        if _cal_status != "APPLIED" and conf > 0:
            # Estimate raw signal from confidence
            if side_str == "long":
                raw_signal = "BUY" if conf > 50 else "HOLD"
            else:
                raw_signal = "SELL" if conf > 50 else "HOLD"
            trade_signal = "BUY" if side_str == "long" else "SELL"
            if raw_signal == trade_signal:
                _uncal_signal_r = realized_r
                _cal_status = "APPLIED"
            elif raw_signal == "HOLD":
                _uncal_signal_r = 0.0
                _cal_status = "APPLIED"
            else:
                _uncal_signal_r = None
                _cal_status = "NOT_AVAILABLE"

        # ── Portfolio attribution ──────────────────────────────────────
        _kelly = trade.get("kelly_multiplier")

        # ── Risk attribution ───────────────────────────────────────────
        _risk_intervention = trade.get("risk_intervention_active", False)

        # ── Profit floor attribution ───────────────────────────────────
        _was_protected = trade.get("profit_lock_held", False) or trade.get("profit_lock_triggered", False)

        # ── Decision ID (pre-computed, uses prov from lookup above) ──
        if store is not None and prov is not None:
            decision_id = str(prov.decision_id.decision_id)
        else:
            decision_id = str(trade.get("attribution_trade_id", ""))

        attribution = self._calculator.calculate(
            trade_id=str(trade.get("trade_id", trade.get("attribution_trade_id", ""))),
            decision_id=decision_id,
            lifecycle_version="v2_profit_floor",
            realized_r=realized_r,
            holding_period_candles=bars,
            exit_reason=exit_reason,
            asset=asset,
            entry_archetype=entry_archetype,
            entry_price=entry_price,
            first_intervention_price=_first_itv_price,
            side=side_str,
            risk_pct=_risk_price,
            static_exit_r=_static_tp_r,
            was_protected=_was_protected,
            calibrated=_calibrated,
            uncalibrated_signal_r=_uncal_signal_r,
            actual_allocation_pct=float(_kelly) if _kelly else None,
            risk_intervention_active=_risk_intervention,
        )
        return attribution.to_dict()

    def _find_provenance_for_trade(
        self, trade: dict, store: SqliteProvenanceStore
    ) -> DecisionProvenance | None:
        """Find the provenance record that matches this trade."""
        asset = str(trade.get("asset", "")).upper()
        entry_date = str(trade.get("entry_date", ""))

        # Query by asset + approximate date range
        records = store.query(
            asset=asset,
            limit=20,
            sort_desc=True,
        )
        if not records:
            return None

        # Find the closest provenances by entry date proximity
        entry_ts = self._parse_timestamp(entry_date)
        if entry_ts is None:
            return records[0] if records else None

        best = None
        best_gap = float("inf")
        for rec in records:
            rec_ts = self._parse_timestamp(rec.decision_timestamp)
            if rec_ts is None:
                continue
            gap = abs((rec_ts - entry_ts).total_seconds())
            # Must be within 1 hour of entry decision
            if gap < best_gap and gap < 3600:
                best_gap = gap
                best = rec

        return best or (records[0] if records else None)

    def _compute_calibration_from_provenance(
        self, prov: DecisionProvenance, actual_side: str, realized_r: float
    ) -> tuple[float | None, str]:
        """Use CounterfactualEngine to compute uncalibrated signal."""
        if prov.model is None or prov.decision is None:
            return None, "NOT_AVAILABLE"

        # The raw probabilities are already in the ModelContext
        raw_long = prov.model.prob_long
        raw_short = prov.model.prob_short
        raw_neutral = prov.model.prob_neutral

        # Run CounterfactualEngine with raw (uncalibrated) probabilities
        cf_prov, delta = self._cf_engine.probability_override(
            original=prov,
            prob_long=raw_long,
            prob_short=raw_short,
            prob_neutral=raw_neutral,
        )

        uncal_signal = cf_prov.decision.final_signal if cf_prov.decision else "HOLD"
        trade_signal = "BUY" if actual_side == "long" else "SELL"

        if uncal_signal == trade_signal:
            return realized_r, "APPLIED"
        elif uncal_signal == "HOLD":
            return 0.0, "APPLIED"
        else:
            return 0.0, "APPLIED"

    def _parse_timestamp(self, ts: str) -> datetime | None:
        """Parse various timestamp formats."""
        if not ts:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(ts.replace("Z", "+0000"), fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    def summarize(self, result: ReplayResult) -> dict:
        """Build a human-readable summary dict."""
        layer_breakdown = {}
        for layer in ("entry", "calibration", "exit", "profit_floor", "portfolio", "risk"):
            total = result.total_attributed_r.get(layer, 0.0)
            layer_breakdown[layer] = {
                "total_r": round(total, 2),
                "pct_of_realized": round(total / result.total_realized_r * 100, 1) if result.total_realized_r != 0 else 0.0,
            }

        return {
            "n_trades": result.n_trades,
            "n_with_provenance": result.n_with_provenance,
            "n_with_calibration_delta": result.n_with_calibration_delta,
            "total_realized_r": round(result.total_realized_r, 2),
            "calibration_delta_r": round(result.calibration_delta_r, 2),
            "layer_breakdown": layer_breakdown,
            "by_asset": {
                asset: {
                    "n_trades": len(tlist),
                    "realized_r": round(sum(t.get("realized_r", 0.0) or 0.0 for t in tlist), 2),
                }
                for asset, tlist in sorted(result.trades.items())
            },
        }


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Offline attribution replay")
    parser.add_argument("--trades", default=TRADES_DEFAULT, help="Path to trade lifecycle results JSON")
    parser.add_argument("--provenance-db", default=PROVENANCE_DB_DEFAULT, help="Path to provenance SQLite db")
    parser.add_argument("--asset", default=None, help="Filter by asset name")
    parser.add_argument("--limit", type=int, default=0, help="Max trades to process")
    parser.add_argument("--output", default=None, help="Output path for enriched trades JSON")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(name)s %(levelname)s %(message)s",
    )

    replay = AttributionReplay(provenance_db=args.provenance_db)
    result = replay.run(trades_source=args.trades, asset_filter=args.asset, limit=args.limit)
    summary = replay.summarize(result)

    print(json.dumps(summary, indent=2))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(dict(result.trades), f, indent=2)
        print(f"Wrote {result.n_trades} enriched trades to {output_path}")


if __name__ == "__main__":
    main()
