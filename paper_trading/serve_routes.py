import json
import os
from dataclasses import asdict
from datetime import datetime

import pytz

from features.fxstreet_fetcher import confirm_pending_narrative, get_narrative_status
from paper_trading.config_manager import get_config
from paper_trading.health_score import compute_all as _compute_health_all
from paper_trading.health_score import get_latest as _get_health_latest
from paper_trading.market_hours import is_market_closed
from paper_trading.portfolio_builder import build_paper_portfolio
from paper_trading.risk_governance import get_latest as _get_risk_latest
from paper_trading.serve_common import (
    _STORE,
    CONFIDENCE_PATH,
    LOG_PATH,
    cache_get,
    cache_set,
    get_vol_baselines,
)
from paper_trading.weekly_review import compute_weekly_review

ET = pytz.timezone("US/Eastern")


def handle_state(path: str, query: dict) -> str:
    cached = cache_get(path)
    if cached is not None:
        return cached
    snapshot = _STORE.load_snapshot()
    if snapshot is not None:
        state = asdict(snapshot)
        status = state.setdefault("engine_status", {})
        status["market_closed"] = is_market_closed()
        if "last_update" not in status or status["last_update"] is None:
            status["last_update"] = state.get("timestamp", "")
        data = json.dumps(state, indent=2, default=str)
    else:
        cfg = get_config()
        pf = build_paper_portfolio(cfg.halt)
        data = json.dumps(
            {
                "engine_status": {
                    "initialized": True,
                    "last_update": None,
                    "start_time": None,
                    "market_closed": is_market_closed(),
                },
                "portfolio": {
                    "total_value": 0,
                    "total_return": 0,
                    "days_running": 0,
                    "runtime_hours": 0,
                    "start_date": "",
                    "start_datetime": "",
                    "last_update": None,
                    "capital": cfg.capital,
                    "allocations": {n: spec["alloc"] for n, spec in pf.items()},
                    "satellite_allocation_pct": 5.0,
                    "deployment_cleared": True,
                    "open_positions": 0,
                    "closed_trades": 0,
                    "execution_state": "ACTIVE",
                    "average_validity_exposure": 1.0,
                },
                "assets": {},
                "halt_conditions": dict(cfg.halt),
            },
            indent=2,
        )
    cache_set("/state.json", data)
    return data


def handle_trades(path: str, query: dict) -> str:
    limit = max(1, min(int(query.get("limit", 10)), 200))
    offset = max(0, int(query.get("offset", 0)))
    trades = _STORE.read_trades(limit + offset)

    seen = set()
    deduped = []

    def _sig(t):
        return (
            t.get("asset"),
            t.get("entry_date"),
            t.get("exit_date"),
            t.get("reason"),
            round(t.get("entry", 0), 4),
            round(t.get("exit", 0), 4),
        )

    for t in trades:
        s = _sig(t)
        if s not in seen:
            seen.add(s)
            deduped.append(t)

    if len(deduped) < limit + offset:
        snapshot = _STORE.load_snapshot()
        if snapshot and snapshot.assets:
            for aname, adata in snapshot.assets.items():
                metrics = adata.get("metrics") or {}
                trade_log = metrics.get("trade_log") or []
                for t in trade_log:
                    if t.get("exit_date") is None:
                        continue
                    s = _sig(t)
                    if s not in seen:
                        seen.add(s)
                        deduped.append(t)
            deduped = sorted(deduped, key=lambda x: x.get("exit_date", ""), reverse=True)

    seen2 = set()
    final = []
    for t in deduped:
        k = (t.get("asset"), t.get("entry_date"), t.get("exit_date"), t.get("reason"))
        if k not in seen2:
            seen2.add(k)
            final.append(t)
    deduped = final

    data = json.dumps(deduped[offset : offset + limit], default=str)
    cache_set(path, data)
    return data


def handle_equity_history(path: str, query: dict) -> str:
    history = _STORE.read_equity_history()
    data = json.dumps(history, default=str)
    cache_set("/equity_history.json", data)
    return data


def handle_confidence(path: str, query: dict) -> str:
    cached = cache_get(path)
    if cached is not None:
        return cached
    snapshot = _STORE.load_snapshot()
    if snapshot and snapshot.assets:
        live = {}
        for name, asset in snapshot.assets.items():
            sig = asset.get("last_signal") or {}
            conf = sig.get("confidence", 0)
            bucket_low = min(int(conf // 10) * 10, 90)
            bucket = f"{bucket_low}-{bucket_low + 10}"
            live.setdefault(name, {})
            live[name][bucket] = live[name].get(bucket, 0) + 1
        historical = []
        try:
            if os.path.exists(CONFIDENCE_PATH):
                import pandas as pd

                df = pd.read_parquet(CONFIDENCE_PATH)
                historical = json.loads(df.to_json(orient="records", default_handler=str))
        except Exception:
            pass
        data = json.dumps({"live": live, "historical": historical}, indent=2, default=str)
    else:
        data = json.dumps({"live": {}, "historical": []})
    cache_set("/confidence.json", data)
    return data


def handle_volatility(path: str, query: dict) -> str:
    snapshot = _STORE.load_snapshot()
    regimes = []
    vol_baselines = get_vol_baselines()
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            training_vol = vol_baselines.get(name)
            metrics = asset.get("metrics") or {}
            pos = metrics.get("position") or {}
            current_vol = pos.get("current_vol") if pos else None
            if training_vol is not None and current_vol is not None:
                ratio = current_vol / training_vol
                if 0.80 <= ratio <= 1.20:
                    status = "green"
                elif (0.70 <= ratio < 0.80) or (1.20 < ratio <= 1.30):
                    status = "amber"
                else:
                    status = "red"
                regimes.append(
                    {
                        "asset": name,
                        "training_vol": training_vol,
                        "current_vol": current_vol,
                        "ratio": round(ratio, 4),
                        "status": status,
                    }
                )
    data = json.dumps(regimes, indent=2, default=str)
    cache_set("/volatility.json", data)
    return data


def handle_logs(path: str, query: dict) -> str:
    try:
        with open(LOG_PATH) as f:
            lines = f.readlines()
        boundary = None
        for i in range(len(lines) - 1, -1, -1):
            if "Server stopped." in lines[i]:
                boundary = i + 1
                break
        tail = "".join(lines[boundary:][-200:]) if boundary is not None else "".join(lines[-200:])
        return tail
    except FileNotFoundError:
        return "[no log file yet]"


def handle_risk(path: str, query: dict) -> str:
    data = json.dumps(_get_risk_latest(), indent=2, default=str)
    cache_set("/risk.json", data)
    return data


def handle_risk_asset(path: str, query: dict) -> tuple[str, int]:
    asset = path[len("/risk/") : -len(".json")]
    signal = _get_risk_latest(asset)
    if signal is not None:
        return json.dumps(signal, indent=2, default=str), 200
    return json.dumps({"error": f"No risk signal for {asset}", "asset": asset}), 404


def handle_shadow_actions(path: str, query: dict) -> str:
    snapshot = _STORE.load_snapshot()
    actions = getattr(snapshot, "shadow_actions", None) if snapshot else None
    data = json.dumps(actions or {}, indent=2, default=str)
    cache_set("/shadow-actions", data)
    return data


def handle_shadow_actions_asset(path: str, query: dict) -> tuple[str, int]:
    asset = path[len("/shadow-actions/") : -len(".json")]
    snapshot = _STORE.load_snapshot()
    actions = getattr(snapshot, "shadow_actions", None) if snapshot else None
    action = (actions or {}).get(asset)
    if action is not None:
        return json.dumps(action, indent=2, default=str), 200
    return json.dumps({"error": f"No shadow action for {asset}", "asset": asset}), 404


def handle_health(path: str, query: dict) -> str:
    data = json.dumps(_compute_health_all(), indent=2, default=str)
    cache_set("/health.json", data)
    return data


def handle_health_asset(path: str, query: dict) -> tuple[str, int]:
    asset = path[len("/health/") : -len(".json")]
    signal = _get_health_latest(asset)
    if signal is not None:
        return json.dumps(signal, indent=2, default=str), 200
    return json.dumps({"error": f"No health score for {asset}", "asset": asset}), 404


def handle_governance(path: str, query: dict) -> str:
    snapshot = _STORE.load_snapshot()
    governance = {}
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            regime_sl = 1.0
            regime_size = 1.0
            validity = (asset.get("validity_state") or "YELLOW").upper()
            rg = (asset.get("regime_geometry") or {}).get(validity, {})
            regime_sl = rg.get("sl_mult", 1.0)
            regime_size = rg.get("tp_mult", 1.0)
            narr_sl = asset.get("narrative_sl_mult", 1.0)
            narr_size = asset.get("narrative_size_scalar", 1.0)
            liq_sl = asset.get("liquidity_sl_mult", 1.0)
            liq_size = asset.get("liquidity_size_scalar", 1.0)
            combined_sl = regime_sl * narr_sl * liq_sl
            raw_size = regime_size * narr_size * liq_size
            combined_size = max(raw_size, 0.30)
            governance[name] = {
                "regime_sl_mult": regime_sl,
                "regime_size_scalar": regime_size,
                "narrative_sl_mult": narr_sl,
                "narrative_size_scalar": narr_size,
                "liquidity_sl_mult": liq_sl,
                "liquidity_size_scalar": liq_size,
                "combined_sl_mult": round(combined_sl, 4),
                "combined_size_scalar": round(combined_size, 4),
                "floor_active": combined_size == 0.30,
                "validity_state": validity,
                "narrative_regime": asset.get("narrative_regime"),
                "narrative_stale": asset.get("narrative_stale", False),
                "liquidity_regime": asset.get("liquidity_regime", "NORMAL"),
                "halted": asset.get("halt", {}).get("halted", False),
            }
    data = json.dumps(governance, indent=2, default=str)
    cache_set("/governance.json", data)
    return data


def handle_risk_parity(path: str, query: dict) -> str:
    snapshot = _STORE.load_snapshot()
    rp = getattr(snapshot, "risk_parity", None) if snapshot else None
    data = json.dumps(rp or {}, indent=2, default=str)
    cache_set("/risk-parity.json", data)
    return data


def handle_narrative(path: str, query: dict) -> str:
    status = get_narrative_status()
    data = json.dumps(status, indent=2, default=str)
    cache_set("/narrative.json", data)
    return data


def handle_liquidity(path: str, query: dict) -> str:
    snapshot = _STORE.load_snapshot()
    regimes = {}
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            regimes[name] = {
                "regime": asset.get("liquidity_regime", "NORMAL"),
                "sl_mult": asset.get("liquidity_sl_mult", 1.0),
                "size_scalar": asset.get("liquidity_size_scalar", 1.0),
            }
    data = json.dumps(regimes, indent=2, default=str)
    cache_set("/liquidity.json", data)
    return data


def handle_psi(path: str, query: dict) -> str:
    snapshot = _STORE.load_snapshot()
    psi_data = {}
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            metrics = asset.get("metrics", {})
            psi = metrics.get("psi_drift", {})
            if psi and psi.get("per_feature"):
                psi_data[name] = {
                    "per_feature": psi["per_feature"],
                    "worst_classification": psi.get("worst_classification", "NO_DRIFT"),
                    "moderate_count": psi.get("moderate_count", 0),
                    "severe_count": psi.get("severe_count", 0),
                    "psi_ok": psi.get("psi_ok", True),
                    "penalty": psi.get("penalty", 0.0),
                }
    data = json.dumps(psi_data, indent=2, default=str)
    cache_set("/psi.json", data)
    return data


def handle_trade_outcomes(path: str, query: dict) -> str:
    outcomes = _STORE.read_trade_outcomes()
    if outcomes is None:
        outcomes = {"overall": {}, "by_asset": [], "updated_at": ""}
    data = json.dumps(outcomes, indent=2, default=str)
    cache_set("/trade-outcomes.json", data)
    return data


def handle_weekly_review(path: str, query: dict) -> str:
    data = json.dumps(compute_weekly_review(_STORE), indent=2, default=str)
    cache_set("/weekly-review.json", data)
    return data


def handle_ping(path: str, query: dict) -> str:
    return json.dumps({"status": "ok"}, indent=2)


def handle_narrative_confirm(body: bytes) -> tuple[str, int]:
    ok = confirm_pending_narrative()
    if ok:
        return json.dumps({"status": "confirmed", "message": "Narrative confirmed"}, indent=2), 200
    return (
        json.dumps({"status": "error", "message": "No pending narrative to confirm"}, indent=2),
        400,
    )


def handle_weekly_review_acknowledge(body: bytes) -> tuple[str, int]:
    now = datetime.now(tz=ET).isoformat()
    entry = {"acknowledged_at": now}
    rlp = _STORE.review_log_path
    existing = []
    if os.path.exists(rlp):
        try:
            with open(rlp) as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.append(entry)
    with open(rlp, "w") as f:
        json.dump(existing, f, indent=2)
    return json.dumps({"status": "ok", "acknowledged_at": now}, indent=2), 200


# ── Phase 2: Analytics Layer Handlers ──────────────────────────────


def handle_attribution_trades(path: str, query: dict) -> str:
    """Read attribution records from parquet with optional filters.

    Query params: limit, offset, archetype, regime, asset
    Read-only — never mutates engine state.
    """
    limit = max(1, min(int(query.get("limit", 50)), 500))
    offset = max(0, int(query.get("offset", 0)))
    archetype = query.get("archetype") or None
    regime = query.get("regime") or None
    asset = query.get("asset") or None
    records = _STORE.read_attribution(
        limit=limit, offset=offset,
        archetype=archetype, regime=regime, asset=asset,
    )
    data = json.dumps(records, indent=2, default=str)
    cache_set("/attribution/trades.json", data)
    return data


def handle_attribution_summary(path: str, query: dict) -> str:
    """Aggregate attribution summary — precomputed snapshot or computed live.

    Returns per-archetype and per-regime performance deltas.
    Computation is parquet-read-only, no engine dependency.
    """
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    all_records = _STORE.read_attribution(limit=limit)
    if not all_records:
        return json.dumps({"by_archetype": {}, "by_regime": {}, "overall": {}}, indent=2)

    import pandas as pd
    df = pd.DataFrame(all_records)
    overall = {
        "n_trades": len(df),
        "total_pnl": float(df.get("realized_pnl", df.get("realized_return", 0)).sum()),
        "avg_r": float(df.get("exit_realized_r", df.get("realized_r", 0)).mean()),
        "win_rate": float((df.get("exit_realized_r", df.get("realized_r", 0)) > 0).mean()),
    }

    by_archetype = {}
    arch_col = "pred_archetype_at_entry"
    if arch_col in df.columns:
        for arch, grp in df.groupby(arch_col):
            by_archetype[arch] = {
                "n": len(grp),
                "avg_r": float(grp.get("exit_realized_r", 0).mean()),
                "win_rate": float((grp.get("exit_realized_r", 0) > 0).mean()),
                "avg_entry_slippage": float(grp.get("friction_entry_slippage_bps", 0).mean()),
                "avg_exit_slippage": float(grp.get("friction_exit_slippage_bps", 0).mean()),
                "avg_mae": float(grp.get("exit_mae", 0).mean()),
                "avg_mfe": float(grp.get("exit_mfe", 0).mean()),
                "tp_rate": float((grp.get("exit_exit_reason", "") == "tp").mean()),
                "sl_rate": float((grp.get("exit_exit_reason", "") == "sl").mean()),
            }

    by_regime = {}
    regime_col = "pred_regime_at_entry"
    if regime_col in df.columns:
        for reg, grp in df.groupby(regime_col):
            by_regime[reg] = {
                "n": len(grp),
                "avg_r": float(grp.get("exit_realized_r", 0).mean()),
                "win_rate": float((grp.get("exit_realized_r", 0) > 0).mean()),
            }

    data = json.dumps({
        "overall": overall,
        "by_archetype": by_archetype,
        "by_regime": by_regime,
        "updated_at": datetime.now(tz=ET).isoformat(),
    }, indent=2, default=str)
    cache_set("/attribution/summary.json", data)
    return data


def handle_execution_quality(path: str, query: dict) -> str:
    """Execution quality metrics per asset — read from attribution + trade journal.

    Computes EIS (Execution Impact Score) and FQI (Fill Quality Index)
    per asset as deterministic parquet-derived aggregates.
    """
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = _STORE.read_attribution(limit=limit)
    if not records:
        return json.dumps({"by_asset": {}}, indent=2)

    import pandas as pd
    df = pd.DataFrame(records)

    by_asset = {}
    for asset_name, grp in df.groupby("asset"):
        n = len(grp)
        avg_entry_slippage = float(grp.get("friction_entry_slippage_bps", 0).mean())
        avg_exit_slippage = float(grp.get("friction_exit_slippage_bps", 0).mean())
        avg_latency = float(grp.get("friction_latency_bars", 0).mean())
        gap_rate = float(grp.get("friction_gap_fill", False).mean())
        partial_fill_rate = float(grp.get("friction_partial_fill", False).mean())
        avg_fill_ratio = float(grp.get("friction_fill_qty_ratio", 1.0).mean())

        # Fill Quality Index (FQI)
        fqi = avg_fill_ratio * (1 - gap_rate) * max(0, 1 - avg_latency * 0.02)

        # Execution Impact Score (EIS)
        max_slippage = 50.0
        slippage_ratio = min(avg_entry_slippage / max_slippage, 1.0)
        eis = round(
            0.40 * (1 - slippage_ratio)
            + 0.35 * fqi
            + 0.25 * (1 - partial_fill_rate),
            4,
        )

        by_asset[asset_name] = {
            "n": n,
            "eis": eis,
            "fqi": round(fqi, 4),
            "avg_entry_slippage_bps": round(avg_entry_slippage, 2),
            "avg_exit_slippage_bps": round(avg_exit_slippage, 2),
            "avg_latency_bars": round(avg_latency, 2),
            "gap_rate": round(gap_rate, 4),
            "partial_fill_rate": round(partial_fill_rate, 4),
            "avg_fill_ratio": round(avg_fill_ratio, 4),
        }

    data = json.dumps({"by_asset": by_asset}, indent=2, default=str)
    cache_set("/execution/quality.json", data)
    return data


def handle_execution_slippage(path: str, query: dict) -> str:
    """Slippage distribution from attribution records."""
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = _STORE.read_attribution(limit=limit)
    if not records:
        return json.dumps({"entry_slippage": [], "exit_slippage": []}, indent=2)

    entry_slippage = []
    exit_slippage = []
    gap_count = 0
    partial_count = 0
    for r in records:
        es = r.get("friction_entry_slippage_bps")
        xs = r.get("friction_exit_slippage_bps")
        if es is not None:
            entry_slippage.append(float(es))
        if xs is not None:
            exit_slippage.append(float(xs))
        if r.get("friction_gap_fill"):
            gap_count += 1
        if r.get("friction_partial_fill"):
            partial_count += 1

    data = json.dumps({
        "entry_slippage": entry_slippage,
        "exit_slippage": exit_slippage,
        "gap_count": gap_count,
        "partial_fill_count": partial_count,
        "n": len(records),
    }, indent=2, default=str)
    cache_set("/execution/slippage.json", data)
    return data


def handle_shadow_trades_route(path: str, query: dict) -> str:
    """Read shadow trade records from parquet.

    Query params: limit, offset, alt_label
    Read-only — never mutates engine state or shadow buffers.
    """
    limit = max(1, min(int(query.get("limit", 50)), 500))
    offset = max(0, int(query.get("offset", 0)))
    alt_label = query.get("alt_label") or None
    records = _STORE.read_shadow_trades(limit=limit, offset=offset, alt_label=alt_label)
    data = json.dumps(records, indent=2, default=str)
    cache_set("/shadow/trades.json", data)
    return data


def handle_shadow_summary(path: str, query: dict) -> str:
    """Aggregate shadow vs live divergence summary.

    Computes divergence rates, R-deltas, and outcome reason mismatches
    entirely from parquet — no engine dependency.
    """
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = _STORE.read_shadow_trades(limit=limit)
    if not records:
        return json.dumps({"divergence": {}, "n": 0}, indent=2)

    import pandas as pd
    df = pd.DataFrame(records)

    n = len(df)
    same_reason = (df.get("exit_reason", "") == df.get("live_exit_reason", "")).sum()
    divergence_rate = 1 - (same_reason / n) if n > 0 else 0

    r_delta = df.get("realized_r", 0) - df.get("live_realized_r", 0)
    avg_r_delta = float(r_delta.mean())
    r_delta_std = float(r_delta.std())

    # Divergence by alt_label (shadow configuration)
    by_label = {}
    for label, grp in df.groupby("alt_label"):
        gn = len(grp)
        gsr = (grp.get("exit_reason", "") == grp.get("live_exit_reason", "")).sum()
        gr_delta = grp.get("realized_r", 0) - grp.get("live_realized_r", 0)
        by_label[label] = {
            "n": gn,
            "divergence_rate": round(1 - gsr / gn, 4) if gn > 0 else 0,
            "avg_r_delta": round(float(gr_delta.mean()), 4),
            "shadow_avg_r": round(float(grp.get("realized_r", 0).mean()), 4),
            "live_avg_r": round(float(grp.get("live_realized_r", 0).mean()), 4),
        }

    data = json.dumps({
        "n": n,
        "divergence_rate": round(divergence_rate, 4),
        "avg_r_delta": round(avg_r_delta, 4),
        "r_delta_std": round(r_delta_std, 4),
        "by_label": by_label,
        "updated_at": datetime.now(tz=ET).isoformat(),
    }, indent=2, default=str)
    cache_set("/shadow/summary.json", data)
    return data


def handle_analytics_snapshot(path: str, query: dict) -> str:
    """Return the precomputed analytics snapshot (fast cache, no parquet read).

    Falls back to live computation if snapshot is stale or missing.
    """
    snapshot = _STORE.read_analytics_snapshot()
    if snapshot is not None:
        return json.dumps(snapshot, indent=2, default=str)
    return json.dumps({"overall": {}, "by_archetype": {}, "by_regime": {}, "shadow": {}}, indent=2)


def handle_archetype_stats(path: str, query: dict) -> str:
    """Per-archetype performance and execution statistics."""
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = _STORE.read_attribution(limit=limit)
    if not records:
        return json.dumps({"by_archetype": {}}, indent=2)

    import pandas as pd
    df = pd.DataFrame(records)
    arch_col = "pred_archetype_at_entry"

    by_archetype = {}
    if arch_col in df.columns:
        for arch, grp in df.groupby(arch_col):
            by_archetype[arch] = {
                "n": len(grp),
                "avg_r": float(grp.get("exit_realized_r", 0).mean()),
                "win_rate": float((grp.get("exit_realized_r", 0) > 0).mean()),
                "tp_rate": float((grp.get("exit_exit_reason", "") == "tp").mean()),
                "sl_rate": float((grp.get("exit_exit_reason", "") == "sl").mean()),
                "avg_mae": float(grp.get("exit_mae", 0).mean()),
                "avg_mfe": float(grp.get("exit_mfe", 0).mean()),
                "avg_entry_slippage_bps": float(grp.get("friction_entry_slippage_bps", 0).mean()),
                "avg_bars_held": float(grp.get("exit_bars_held", 0).mean()),
            }

    data = json.dumps({"by_archetype": by_archetype}, indent=2, default=str)
    cache_set("/archetype/stats.json", data)
    return data


GET_ROUTES: dict[str, tuple] = {
    "/state.json": (handle_state, False),
    "/trades.json": (handle_trades, False),
    "/equity_history.json": (handle_equity_history, False),
    "/confidence.json": (handle_confidence, False),
    "/volatility.json": (handle_volatility, False),
    "/logs": (handle_logs, True),
    "/risk.json": (handle_risk, False),
    "/shadow-actions": (handle_shadow_actions, False),
    "/health.json": (handle_health, False),
    "/governance.json": (handle_governance, False),
    "/risk-parity.json": (handle_risk_parity, False),
    "/narrative.json": (handle_narrative, False),
    "/liquidity.json": (handle_liquidity, False),
    "/psi.json": (handle_psi, False),
    "/trade-outcomes.json": (handle_trade_outcomes, False),
    "/weekly-review.json": (handle_weekly_review, False),
    "/attribution/trades.json": (handle_attribution_trades, False),
    "/attribution/summary.json": (handle_attribution_summary, False),
    "/execution/quality.json": (handle_execution_quality, False),
    "/execution/slippage.json": (handle_execution_slippage, False),
    "/shadow/trades.json": (handle_shadow_trades_route, False),
    "/shadow/summary.json": (handle_shadow_summary, False),
    "/archetype/stats.json": (handle_archetype_stats, False),
    "/analytics/snapshot.json": (handle_analytics_snapshot, False),
    "/ping": (handle_ping, False),
}

GET_ROUTES_PREFIX: list[tuple[str, object, bool]] = [
    ("/risk/", handle_risk_asset, False),
    ("/shadow-actions/", handle_shadow_actions_asset, False),
    ("/health/", handle_health_asset, False),
]

POST_ROUTES: dict[str, object] = {
    "/narrative/confirm": handle_narrative_confirm,
    "/weekly-review/acknowledge": handle_weekly_review_acknowledge,
}
