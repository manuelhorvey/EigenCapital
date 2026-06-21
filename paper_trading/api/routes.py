import json
import os
from dataclasses import asdict
from datetime import datetime

import pytz

from features.fxstreet_fetcher import confirm_pending_narrative, get_narrative_status
from paper_trading.api.common import (
    _STORE,
    CONFIDENCE_PATH,
    LOG_PATH,
    cache_get,
    cache_set,
    get_mt5_status,
    get_vol_baselines,
    json_dumps,
)
from paper_trading.config_manager import get_config
from paper_trading.state_store import CONTRACT_VERSION
from paper_trading.governance.health import compute_all as _compute_health_all
from paper_trading.governance.health import get_latest as _get_health_latest
from paper_trading.governance.multipliers import compute_governance_multipliers
from paper_trading.governance.risk import get_latest as _get_risk_latest
from paper_trading.ops.market_hours import is_market_closed
from paper_trading.ops.weekly_review import compute_weekly_review
from paper_trading.portfolio_builder import build_paper_portfolio
from paper_trading.state_store import CONTRACT_VERSION

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
        # Patch: merge allocations from config for assets present in snapshot
        # but missing from portfolio.allocations (e.g. after adding a new
        # asset to config without re-saving state).
        assets = state.get("assets") or {}
        portfolio = state.get("portfolio") or {}
        if isinstance(portfolio, dict) and isinstance(assets, dict):
            allocs = portfolio.setdefault("allocations", {})
            cfg = get_config()
            pf = build_paper_portfolio(cfg.halt)
            for name in assets:
                if name not in allocs and name in pf:
                    allocs[name] = pf[name]["alloc"]
        data = json_dumps(state)
    else:
        cfg = get_config()
        pf = build_paper_portfolio(cfg.halt)
        data = json_dumps(
            {
                "contract_version": CONTRACT_VERSION,
                "sequence_id": 0,
                "schema_version": "1.0.0",
                "timestamp": datetime.now(tz=ET).isoformat(),
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

    seen: set[tuple] = set()
    deduped: list[dict] = []

    for t in trades:
        key = (
            t.get("asset"),
            t.get("entry_date"),
            t.get("exit_date"),
            t.get("reason"),
            round(t.get("entry", 0), 4),
            round(t.get("exit", 0), 4),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    if len(deduped) < limit + offset:
        snapshot = _STORE.load_snapshot()
        if snapshot and snapshot.assets:
            for aname, adata in snapshot.assets.items():
                for t in (adata.get("metrics") or {}).get("trade_log") or []:
                    exit_date = t.get("exit_date")
                    if exit_date is None:
                        continue
                    key = (
                        t.get("asset"),
                        t.get("entry_date"),
                        exit_date,
                        t.get("reason"),
                        round(t.get("entry", 0), 4),
                        round(t.get("exit", 0), 4),
                    )
                    if key not in seen:
                        seen.add(key)
                        deduped.append(t)
            deduped.sort(key=lambda x: x.get("exit_date", ""), reverse=True)

    data = json_dumps(deduped[offset : offset + limit])
    cache_set(path, data)
    return data


def handle_equity_history(path: str, query: dict) -> str:
    history = _STORE.read_equity_history()
    data = json_dumps(history)
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
            # Normalize 0-1 → 0-100 (confidence can arrive as either scale)
            if conf <= 1:
                conf = conf * 100
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
        data = json_dumps({"live": live, "historical": historical}, indent=2)
    else:
        data = json_dumps({"live": {}, "historical": []})
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
    data = json_dumps(regimes, indent=2)
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
    data = json_dumps(_get_risk_latest(), indent=2)
    cache_set("/risk.json", data)
    return data


def handle_risk_asset(path: str, query: dict) -> tuple[str, int]:
    asset = path[len("/risk/") : -len(".json")]
    signal = _get_risk_latest(asset)
    if signal is not None:
        return json_dumps(signal, indent=2), 200
    return json_dumps({"error": f"No risk signal for {asset}", "asset": asset}), 404


def handle_shadow_actions(path: str, query: dict) -> str:
    snapshot = _STORE.load_snapshot()
    actions = getattr(snapshot, "shadow_actions", None) if snapshot else None
    data = json_dumps(actions or {}, indent=2)
    cache_set("/shadow-actions", data)
    return data


def handle_shadow_actions_asset(path: str, query: dict) -> tuple[str, int]:
    asset = path[len("/shadow-actions/") : -len(".json")]
    snapshot = _STORE.load_snapshot()
    actions = getattr(snapshot, "shadow_actions", None) if snapshot else None
    action = (actions or {}).get(asset)
    if action is not None:
        return json_dumps(action, indent=2), 200
    return json_dumps({"error": f"No shadow action for {asset}", "asset": asset}), 404


def handle_health(path: str, query: dict) -> str:
    data = json_dumps(_compute_health_all(), indent=2)
    cache_set("/health.json", data)
    return data


def handle_health_asset(path: str, query: dict) -> tuple[str, int]:
    asset = path[len("/health/") : -len(".json")]
    signal = _get_health_latest(asset)
    if signal is not None:
        return json_dumps(signal, indent=2), 200
    return json_dumps({"error": f"No health score for {asset}", "asset": asset}), 404


def handle_governance(path: str, query: dict) -> str:
    snapshot = _STORE.load_snapshot()
    governance = {}
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            validity = (asset.get("validity_state") or "YELLOW").upper()
            regime_sl, combined_sl, regime_size, combined_size, floor_active = compute_governance_multipliers(
                validity_state=validity,
                regime_geometry=asset.get("regime_geometry") or {},
                narrative_sl_mult=asset.get("narrative_sl_mult", 1.0),
                liquidity_sl_mult=asset.get("liquidity_sl_mult", 1.0),
                narrative_size_scalar=asset.get("narrative_size_scalar", 1.0),
                liquidity_size_scalar=asset.get("liquidity_size_scalar", 1.0),
            )
            metrics = asset.get("metrics") or {}
            governance[name] = {
                "regime_sl_mult": regime_sl,
                "regime_size_scalar": regime_size,
                "narrative_sl_mult": asset.get("narrative_sl_mult", 1.0),
                "narrative_size_scalar": asset.get("narrative_size_scalar", 1.0),
                "liquidity_sl_mult": asset.get("liquidity_sl_mult", 1.0),
                "liquidity_size_scalar": asset.get("liquidity_size_scalar", 1.0),
                "combined_sl_mult": round(combined_sl, 4),
                "combined_size_scalar": round(combined_size, 4),
                "floor_active": floor_active,
                "validity_state": validity,
                "narrative_regime": asset.get("narrative_regime"),
                "narrative_stale": asset.get("narrative_stale", False),
                "liquidity_regime": asset.get("liquidity_regime", "NORMAL"),
                "halted": asset.get("halt", {}).get("halted", False),
                "soft_warnings": asset.get("soft_warnings", []),
                "crs": metrics.get("crs"),
            }
    data = json_dumps(governance, indent=2)
    cache_set("/governance.json", data)
    return data


def handle_statistical_metrics(path: str, query: dict) -> str:
    """Per-asset PSR, MinTRL, CRS, HHI for the dashboard."""
    snapshot = _STORE.load_snapshot()
    result: dict[str, dict] = {}
    if snapshot and snapshot.assets:
        for name, asset in sorted(snapshot.assets.items()):
            metrics = asset.get("metrics") or {}
            result[name] = {
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "psr_gt_0": metrics.get("psr_gt_0"),
                "psr_gt_1": metrics.get("psr_gt_1"),
                "min_trl": metrics.get("min_trl"),
                "crs": metrics.get("crs"),
                "hhi": metrics.get("hhi"),
            }
    data = json_dumps(result, indent=2)
    cache_set("/statistical-metrics.json", data)
    return data


def handle_risk_parity(path: str, query: dict) -> str:
    snapshot = _STORE.load_snapshot()
    rp = getattr(snapshot, "risk_parity", None) if snapshot else None
    data = json_dumps(rp or {}, indent=2)
    cache_set("/risk-parity.json", data)
    return data


def handle_narrative(path: str, query: dict) -> str:
    status = get_narrative_status()
    data = json_dumps(status, indent=2)
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
    data = json_dumps(regimes, indent=2)
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
    data = json_dumps(psi_data, indent=2)
    cache_set("/psi.json", data)
    return data


def handle_trade_outcomes(path: str, query: dict) -> str:
    outcomes = _STORE.read_trade_outcomes()
    if outcomes is None:
        outcomes = {"overall": {}, "by_asset": [], "updated_at": ""}
    data = json_dumps(outcomes, indent=2)
    cache_set("/trade-outcomes.json", data)
    return data


def handle_weekly_review(path: str, query: dict) -> str:
    data = json_dumps(compute_weekly_review(_STORE), indent=2)
    cache_set("/weekly-review.json", data)
    return data


def handle_ping(path: str, query: dict) -> str:
    return json_dumps({"status": "ok"}, indent=2)


def handle_narrative_confirm(body: bytes) -> tuple[str, int]:
    ok = confirm_pending_narrative()
    if ok:
        return json_dumps({"status": "confirmed", "message": "Narrative confirmed"}, indent=2), 200
    return (
        json_dumps({"status": "error", "message": "No pending narrative to confirm"}, indent=2),
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
    return json_dumps({"status": "ok", "acknowledged_at": now}, indent=2), 200


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
        limit=limit,
        offset=offset,
        archetype=archetype,
        regime=regime,
        asset=asset,
    )
    data = json_dumps(records, indent=2)
    cache_set("/attribution/trades.json", data)
    return data


def handle_attribution_summary(path: str, query: dict) -> str:
    """Aggregate attribution summary via shared/metrics modules."""
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    all_records = _STORE.read_attribution(limit=limit)
    if not all_records:
        return json_dumps({"by_archetype": {}, "by_regime": {}, "overall": {}}, indent=2)

    from shared.metrics.attribution import compute_aggregate_domain_scores
    from shared.metrics.mae_mfe import compute_mae_mfe_stats

    domain_scores = compute_aggregate_domain_scores(all_records)
    mae_mfe = compute_mae_mfe_stats(all_records)

    overall = {
        "n_trades": mae_mfe["overall"]["n"],
        "avg_r": mae_mfe["overall"]["avg_mfe_mae_ratio"],
        "avg_mae_pct": mae_mfe["overall"]["avg_mae_pct"],
        "avg_mfe_pct": mae_mfe["overall"]["avg_mfe_pct"],
        "domain_scores": domain_scores["overall"],
    }

    data = json_dumps(
        {
            "overall": overall,
            "by_archetype": mae_mfe.get("by_archetype", {}),
            "by_regime": mae_mfe.get("by_regime", {}),
            "domain_scores": domain_scores.get("by_archetype", {}),
            "updated_at": datetime.now(tz=ET).isoformat(),
        },
    )
    cache_set("/attribution/summary.json", data)
    return data


def handle_execution_quality(path: str, query: dict) -> str:
    """Execution quality metrics per asset — derived via shared/metrics modules."""
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = _STORE.read_attribution(limit=limit)
    if not records:
        return json_dumps({"by_asset": {}}, indent=2)

    import pandas as pd

    from shared.metrics.eis import compute_eis_from_df
    from shared.metrics.fqi import compute_fqi_from_df

    df = pd.DataFrame(records)
    eis_by_asset = compute_eis_from_df(df)
    fqi_by_asset = compute_fqi_from_df(df)

    _col = "friction_entry_slippage_bps"
    has_entry_slip = _col in df.columns
    _col = "friction_exit_slippage_bps"
    has_exit_slip = _col in df.columns
    has_latency = "friction_latency_bars" in df.columns
    has_gap = "friction_gap_fill" in df.columns
    has_partial = "friction_partial_fill" in df.columns
    has_fill_ratio = "friction_fill_qty_ratio" in df.columns

    by_asset = {}
    for asset_name, grp in df.groupby("asset"):
        n = len(grp)
        by_asset[asset_name] = {
            "n": n,
            "eis": eis_by_asset.get(asset_name),
            "fqi": fqi_by_asset.get(asset_name),
            "avg_entry_slippage_bps": round(float(grp["friction_entry_slippage_bps"].mean()), 2)
            if has_entry_slip
            else 0.0,
            "avg_exit_slippage_bps": round(float(grp["friction_exit_slippage_bps"].mean()), 2)
            if has_exit_slip
            else 0.0,
            "avg_latency_bars": round(float(grp["friction_latency_bars"].mean()), 2) if has_latency else 0.0,
            "gap_rate": round(float(grp["friction_gap_fill"].mean()), 4) if has_gap else 0.0,
            "partial_fill_rate": round(float(grp["friction_partial_fill"].mean()), 4) if has_partial else 0.0,
            "avg_fill_ratio": round(float(grp["friction_fill_qty_ratio"].mean()), 4) if has_fill_ratio else 1.0,
        }

    data = json_dumps({"by_asset": by_asset}, indent=2)
    cache_set("/execution/quality.json", data)
    return data


def handle_execution_slippage(path: str, query: dict) -> str:
    """Slippage distribution from attribution records."""
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = _STORE.read_attribution(limit=limit)
    if not records:
        return json_dumps({"entry_slippage": [], "exit_slippage": []}, indent=2)

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

    data = json_dumps(
        {
            "entry_slippage": entry_slippage,
            "exit_slippage": exit_slippage,
            "gap_count": gap_count,
            "partial_fill_count": partial_count,
            "n": len(records),
        },
    )
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
    data = json_dumps(records, indent=2)
    cache_set("/shadow/trades.json", data)
    return data


def handle_shadow_summary(path: str, query: dict) -> str:
    """Aggregate shadow vs live divergence summary via shared/metrics."""
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = _STORE.read_shadow_trades(limit=limit)
    if not records:
        return json_dumps({"overall": {"n": 0}}, indent=2)

    from shared.metrics.shadow import compute_shadow_divergence

    result = compute_shadow_divergence(records)
    result["updated_at"] = datetime.now(tz=ET).isoformat()
    data = json_dumps(result, indent=2)
    cache_set("/shadow/summary.json", data)
    return data


def handle_analytics_snapshot(path: str, query: dict) -> str:
    """Return the precomputed analytics snapshot (fast cache, no parquet read).

    Falls back to live computation if snapshot is stale or missing.
    """
    snapshot = _STORE.read_analytics_snapshot()
    if snapshot is not None:
        return json_dumps(snapshot, indent=2)
    return json_dumps({"overall": {}, "by_archetype": {}, "by_regime": {}, "shadow": {}}, indent=2)


def handle_attribution_waterfall(path: str, query: dict) -> str:
    """PnL decomposition waterfall via shared/metrics."""
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = _STORE.read_attribution(limit=limit)
    if not records:
        return json_dumps(
            {
                "prediction_pnl": 0.0,
                "execution_cost": 0.0,
                "exit_cost": 0.0,
                "friction_cost": 0.0,
                "net_pnl": 0.0,
                "n": 0,
            },
            indent=2,
        )

    from shared.metrics.attribution import compute_waterfall

    result = compute_waterfall(records)
    result["updated_at"] = datetime.now(tz=ET).isoformat()
    data = json_dumps(result, indent=2)
    cache_set("/attribution/waterfall.json", data)
    return data


def handle_archetype_stats(path: str, query: dict) -> str:
    """Per-archetype performance and execution statistics."""
    limit = max(1, min(int(query.get("limit", 500)), 2000))
    records = _STORE.read_attribution(limit=limit)
    if not records:
        return json_dumps({"by_archetype": {}}, indent=2)

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

    data = json_dumps({"by_archetype": by_archetype}, indent=2)
    cache_set("/archetype/stats.json", data)
    return data


def handle_live_attribution(path: str, query: dict) -> str:
    """Current running MAE/MFE for all open positions."""
    snapshot = _STORE.load_snapshot()
    open_positions = snapshot.open_positions if snapshot else {}
    live = []
    for name, data in open_positions.items():
        pos = data.get("position", {})
        live.append(
            {
                "asset": name,
                "side": pos.get("side"),
                "entry_price": pos.get("entry"),
                "current_value": data.get("current_value"),
                "running_mae": data.get("running_mae"),
                "running_mfe": data.get("running_mfe"),
            }
        )
    result = json_dumps(live, indent=2)
    cache_set("/attribution/live.json", result)
    return result


def handle_mt5_status(path: str, query: dict) -> str:
    data = json_dumps(get_mt5_status(), indent=2)
    cache_set("/mt5/status.json", data)
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
    "/statistical-metrics.json": (handle_statistical_metrics, False),
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
    "/attribution/live.json": (handle_live_attribution, False),
    "/attribution/waterfall.json": (handle_attribution_waterfall, False),
    "/analytics/snapshot.json": (handle_analytics_snapshot, False),
    "/mt5/status.json": (handle_mt5_status, False),
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
