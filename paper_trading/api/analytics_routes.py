from datetime import datetime

import pytz

from paper_trading.api.common import (
    _STORE,
    cache_set,
    json_dumps,
)

ET = pytz.timezone("US/Eastern")


def handle_attribution_trades(path: str, query: dict) -> str:
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


def handle_attribution_waterfall(path: str, query: dict) -> str:
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


def handle_analytics_snapshot(path: str, query: dict) -> str:
    snapshot = _STORE.read_analytics_snapshot()
    if snapshot is not None:
        return json_dumps(snapshot, indent=2)
    return json_dumps({"overall": {}, "by_archetype": {}, "by_regime": {}, "shadow": {}}, indent=2)


def handle_live_attribution(path: str, query: dict) -> str:
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


def handle_archetype_stats(path: str, query: dict) -> str:
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


def handle_execution_quality(path: str, query: dict) -> str:
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
