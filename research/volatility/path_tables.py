"""Trade-path table builders for the research report deliverables.

Descriptive only: summarises an already-computed path-metrics frame.
Never produces trading labels or recommendations.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from research.volatility import config as C
from research.volatility import evidence as E

PATH_METRICS = [
    "holding_bars",
    "first_profit_bar",
    "time_to_mae",
    "time_to_mfe",
    "max_underwater_run",
    "underwater_fraction",
    "mae_ret",
    "mae_sigma",
    "mfe_ret",
    "mfe_sigma",
    "crossings_per_bar",
    "entry_crossings",
    "path_efficiency",
    "net_pnl",
    "costs",
    "exit_u_ret",
]


def _pct(s: pd.Series, q: float) -> float | None:
    v = pd.to_numeric(s, errors="coerce").dropna()
    if v.empty:
        return None
    return float(v.quantile(q))


def summarize_groups(frame: pd.DataFrame, by: list[str]) -> dict[str, Any]:
    """Median + percentile summary of PATH_METRICS grouped by ``by`` columns."""
    out: dict[str, Any] = {}
    if frame.empty or any(c not in frame.columns for c in by):
        return out
    for keys, grp in frame.groupby(by, dropna=False, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        key = "|".join(str(k) for k in keys)
        cell: dict[str, Any] = {"n": int(len(grp))}
        for m in PATH_METRICS:
            if m not in grp.columns:
                continue
            s = pd.to_numeric(grp[m], errors="coerce")
            if s.notna().sum() == 0:
                cell[m] = {"n": 0}
                continue
            cell[m] = {
                "n": int(s.notna().sum()),
                "mean": float(s.mean()),
                "median": float(s.median()),
                "p25": _pct(s, 0.25),
                "p75": _pct(s, 0.75),
                "p90": _pct(s, 0.90),
                "p95": _pct(s, 0.95),
            }
        if "trade_type" in grp.columns:
            cell["trade_types"] = grp["trade_type"].value_counts().to_dict()
        if "exit_u_ret" in grp.columns:
            cell["win_rate"] = float((pd.to_numeric(grp["exit_u_ret"], errors="coerce") > 0).mean())
        if "side" in grp.columns:
            cell["sides"] = grp["side"].value_counts().to_dict()
        out[key] = cell
        E.LEDGER.count(f"path_table_group:{'+'.join(by)}")
    return out


def per_asset_trade_path_table(frame: pd.DataFrame) -> dict[str, Any]:
    """§52: one summary row-set per asset (sufficient-n gate)."""
    out: dict[str, Any] = {}
    if "asset" not in frame.columns:
        return out
    for asset, grp in frame.groupby("asset"):
        n = int(len(grp))
        cell: dict[str, Any] = {"n_trades": n}
        if n < C.MIN_CELL_TRADES:
            cell["verdict"] = E.INSUFFICIENT_DATA
            out[str(asset)] = cell
            continue
        for m in PATH_METRICS:
            if m not in grp.columns:
                continue
            s = pd.to_numeric(grp[m], errors="coerce")
            cell[m] = {
                "n": int(s.notna().sum()),
                "median": float(s.median()) if s.notna().any() else None,
                "mean": float(s.mean()) if s.notna().any() else None,
                "p25": _pct(s, 0.25),
                "p75": _pct(s, 0.75),
                "p90": _pct(s, 0.90),
                "p95": _pct(s, 0.95),
            }
        if "trade_type" in grp.columns:
            cell["trade_types"] = grp["trade_type"].value_counts().to_dict()
        cell["win_rate"] = float((pd.to_numeric(grp["exit_u_ret"], errors="coerce") > 0).mean())
        cell["no_profit_rate"] = float(pd.to_numeric(grp["first_profit_bar"], errors="coerce").isna().mean())
        out[str(asset)] = cell
        E.LEDGER.count("path_table:per_asset")
    return out


def per_asset_regime_table(frame: pd.DataFrame) -> dict[str, Any]:
    """§53: asset × entry-regime cells; n < MIN_CELL → INSUFFICIENT DATA."""
    out: dict[str, Any] = {}
    if "asset" not in frame.columns:
        return out
    for col, regime_name in (("entry_regime", "percentile_pit"), ("entry_regime_z", "zscore")):
        if col not in frame.columns:
            continue
        by_asset: dict[str, Any] = {}
        for asset, grp in frame.groupby("asset"):
            cells: dict[str, Any] = {}
            for reg in C.REGIME_LABELS:
                sub = grp[grp[col] == reg]
                n = int(len(sub))
                if n < C.MIN_CELL_TRADES:
                    cells[reg] = {"n": n, "verdict": E.INSUFFICIENT_DATA}
                    continue
                cell: dict[str, Any] = {"n": n}
                for m in PATH_METRICS:
                    if m not in sub.columns:
                        continue
                    s = pd.to_numeric(sub[m], errors="coerce")
                    cell[m] = {
                        "median": float(s.median()) if s.notna().any() else None,
                        "p25": _pct(s, 0.25),
                        "p75": _pct(s, 0.75),
                    }
                cell["win_rate"] = float((pd.to_numeric(sub["exit_u_ret"], errors="coerce") > 0).mean())
                cells[reg] = cell
                E.LEDGER.count(f"path_table:asset_regime:{regime_name}")
            by_asset[str(asset)] = cells
        out[regime_name] = by_asset
    return out


def volatility_trade_path_matrix(frame: pd.DataFrame) -> dict[str, Any]:
    """§54: entry-regime × resolution-speed descriptive matrix.

    Resolution-speed buckets are fixed ex-ante from the strategy's own
    geometry (weekly rebalance, modal holding 6 bars):
      fast      : first_profit_bar <= 1  (immediate)
      moderate  : 2 <= first_profit_bar <= 3
      slow      : first_profit_bar >= 4
      no_profit : first_profit_bar is null (NO_PROFIT_BEFORE_EXIT)
    Percentile tertiles were rejected: >50% of profitable trades resolve in
    1 bar, so p33 and p67 both collapse to 1 (empty middle bucket).
    Counts are trades; cell rates are share within the regime row.
    """
    out: dict[str, Any] = {
        "definition": {
            "rows": "entry_regime (percentile PIT)",
            "cols": ["fast", "moderate", "slow", "no_profit"],
            "speed_rule": (
                "fast: first_profit_bar<=1; moderate: 2..3; slow: >=4; "
                "no_profit: null (strategy geometry: modal holding 6 bars, "
                "weekly rebalance; ex-ante, not fitted to outcomes)"
            ),
        },
        "by_regime": {},
        "by_regime_z": {},
    }
    if "entry_regime" not in frame.columns:
        return out

    fp = pd.to_numeric(frame.get("first_profit_bar"), errors="coerce")
    cols = ["fast", "moderate", "slow", "no_profit"]

    def _bucket(row_fp: float | None) -> str:
        if row_fp is None or (isinstance(row_fp, float) and not np.isfinite(row_fp)):
            return "no_profit"
        if row_fp <= 1:
            return "fast"
        if row_fp <= 3:
            return "moderate"
        return "slow"

    work = frame.copy()
    work["_speed"] = [_bucket(v) for v in fp.tolist()]
    out["thresholds"] = {"fast_le": 1.0, "moderate_le": 3.0, "slow_ge": 4.0}

    for col, key in (("entry_regime", "by_regime"), ("entry_regime_z", "by_regime_z")):
        if col not in work.columns:
            continue
        table: dict[str, Any] = {}
        for reg in C.REGIME_LABELS:
            sub = work[work[col] == reg]
            n = int(len(sub))
            if n < C.MIN_CELL_TRADES:
                table[reg] = {"n": n, "verdict": E.INSUFFICIENT_DATA}
                continue
            counts = sub["_speed"].value_counts()
            shares = {c: float(counts.get(c, 0) / n) for c in cols}
            cell: dict[str, Any] = {"n": n, "counts": {c: int(counts.get(c, 0)) for c in cols}, "shares": shares}
            # median resolution among profitable
            med_fp = pd.to_numeric(sub["first_profit_bar"], errors="coerce").median()
            cell["median_time_to_first_profit"] = float(med_fp) if pd.notna(med_fp) else None
            cell["median_max_underwater_run"] = (
                float(pd.to_numeric(sub["max_underwater_run"], errors="coerce").median())
                if "max_underwater_run" in sub
                else None
            )
            cell["median_crossings_per_bar"] = (
                float(pd.to_numeric(sub["crossings_per_bar"], errors="coerce").median())
                if "crossings_per_bar" in sub
                else None
            )
            table[reg] = cell
            E.LEDGER.count(f"vol_x_path_matrix:{key}")
        out[key] = table
    return out


def cost_analysis(frame: pd.DataFrame) -> dict[str, Any]:
    """§37: cost vs excursion structure (canonical cost model unchanged)."""
    out: dict[str, Any] = {"note": "costs = 2 * R4_COST_ONE_WAY * |weight| (frozen model)"}
    if frame.empty:
        return out
    g = frame.groupby("asset") if "asset" in frame.columns else [("ALL", frame)]
    by_asset: dict[str, Any] = {}
    for asset, grp in g if not isinstance(g, pd.DataFrame) else [("ALL", frame)]:
        if len(grp) < C.MIN_CELL_TRADES:
            by_asset[str(asset)] = {"n": int(len(grp)), "verdict": E.INSUFFICIENT_DATA}
            continue
        mfe = pd.to_numeric(grp["mfe_ret"], errors="coerce")
        costs = pd.to_numeric(grp["costs"], errors="coerce")
        w = pd.to_numeric(grp["entry_weight"], errors="coerce").abs()
        # asset-space cost = costs / |weight|
        asset_cost = (costs / w.replace(0, np.nan)).dropna()
        cost_over_mfe = (asset_cost / mfe).replace([np.inf, -np.inf], np.nan).dropna()
        by_asset[str(asset)] = {
            "n": int(len(grp)),
            "mean_costs_portfolio": float(costs.mean()),
            "median_costs_portfolio": float(costs.median()),
            "median_cost_asset_space": float(asset_cost.median()) if len(asset_cost) else None,
            "median_cost_over_mfe": float(cost_over_mfe.median()) if len(cost_over_mfe) else None,
            "frac_cost_exceeds_mfe": float((cost_over_mfe > 1).mean()) if len(cost_over_mfe) else None,
            "mean_gross_pnl": float(pd.to_numeric(grp["gross_pnl"], errors="coerce").mean()),
            "mean_net_pnl": float(pd.to_numeric(grp["net_pnl"], errors="coerce").mean()),
            "mean_exit_u_ret": float(pd.to_numeric(grp["exit_u_ret"], errors="coerce").mean()),
        }
        E.LEDGER.count("cost_analysis:per_asset")
    by_regime: dict[str, Any] = {}
    if "entry_regime" in frame.columns:
        for reg in C.REGIME_LABELS:
            sub = frame[frame["entry_regime"] == reg]
            if len(sub) < C.MIN_CELL_TRADES:
                by_regime[reg] = {"n": int(len(sub)), "verdict": E.INSUFFICIENT_DATA}
                continue
            mfe = pd.to_numeric(sub["mfe_ret"], errors="coerce")
            costs = pd.to_numeric(sub["costs"], errors="coerce")
            w = pd.to_numeric(sub["entry_weight"], errors="coerce").abs()
            ac = (costs / w.replace(0, np.nan)).dropna()
            ratio = (ac / mfe).replace([np.inf, -np.inf], np.nan).dropna()
            by_regime[reg] = {
                "n": int(len(sub)),
                "median_cost_over_mfe": float(ratio.median()) if len(ratio) else None,
                "frac_cost_exceeds_mfe": float((ratio > 1).mean()) if len(ratio) else None,
                "mean_net_pnl": float(pd.to_numeric(sub["net_pnl"], errors="coerce").mean()),
            }
            E.LEDGER.count("cost_analysis:by_regime")
    # F5 companion: does underwater persist after cost recovery?
    if "max_underwater_run_net" in frame.columns and "max_underwater_run" in frame.columns:
        # leave spearman to hypotheses; here only descriptive delta
        out["mean_max_uw_price"] = float(pd.to_numeric(frame["max_underwater_run"], errors="coerce").mean())
        out["mean_max_uw_net"] = float(pd.to_numeric(frame["max_underwater_run_net"], errors="coerce").mean())
        out["median_uw_fraction"] = float(pd.to_numeric(frame["underwater_fraction"], errors="coerce").median())
        out["median_uw_fraction_net"] = (
            float(pd.to_numeric(frame["underwater_fraction_net"], errors="coerce").median())
            if "underwater_fraction_net" in frame.columns
            else None
        )
    out["by_asset"] = by_asset
    out["by_entry_regime"] = by_regime
    return out


def survival_time_to_event(frame: pd.DataFrame) -> dict[str, Any]:
    """§35: descriptive time-to-event (no complex survival models)."""
    out: dict[str, Any] = {}
    if frame.empty:
        return out
    fp = pd.to_numeric(frame["first_profit_bar"], errors="coerce")
    out["first_profit"] = {
        "n": int(fp.notna().sum()),
        "n_censored_no_profit": int(fp.isna().sum()),
        "censor_rate": float(fp.isna().mean()),
        "median_bars": float(fp.median()) if fp.notna().any() else None,
        "p25": _pct(fp, 0.25),
        "p75": _pct(fp, 0.75),
        "mean_bars": float(fp.mean()) if fp.notna().any() else None,
    }
    if "time_to_mfe" in frame.columns:
        tm = pd.to_numeric(frame["time_to_mfe"], errors="coerce")
        out["time_to_mfe"] = {
            "n": int(tm.notna().sum()),
            "median": float(tm.median()) if tm.notna().any() else None,
            "p25": _pct(tm, 0.25),
            "p75": _pct(tm, 0.75),
        }
    if "time_to_large_favorable" in frame.columns:
        tl = pd.to_numeric(frame["time_to_large_favorable"], errors="coerce")
        large = frame.get("large_favorable")
        out["time_to_large_favorable"] = {
            "n_large": int(large.sum()) if large is not None else 0,
            "median_among_large": float(tl.median()) if tl.notna().any() else None,
            "p25": _pct(tl, 0.25),
            "p75": _pct(tl, 0.75),
        }
    # by entry regime medians (descriptive survival-style table)
    if "entry_regime" in frame.columns:
        by_reg: dict[str, Any] = {}
        for reg in C.REGIME_LABELS:
            sub = frame[frame["entry_regime"] == reg]
            if len(sub) < C.MIN_CELL_TRADES:
                by_reg[reg] = {"n": int(len(sub)), "verdict": E.INSUFFICIENT_DATA}
                continue
            s = pd.to_numeric(sub["first_profit_bar"], errors="coerce")
            by_reg[reg] = {
                "n": int(len(sub)),
                "censor_rate": float(s.isna().mean()),
                "median_time_to_first_profit": float(s.median()) if s.notna().any() else None,
                "median_time_to_mfe": float(pd.to_numeric(sub["time_to_mfe"], errors="coerce").median())
                if "time_to_mfe" in sub
                else None,
            }
            E.LEDGER.count("survival:by_regime")
        out["by_entry_regime"] = by_reg
    return out


def cluster_path_link(frame: pd.DataFrame, cluster_labels: dict[str, int]) -> dict[str, Any]:
    """§40: do volatility clusters share trade-path behavior?"""
    out: dict[str, Any] = {
        "note": "descriptive: path medians by full-sample volatility cluster; no causal claim",
    }
    if frame.empty or "asset" not in frame.columns:
        return out
    lab = frame["asset"].map(cluster_labels)
    work = frame.assign(_cluster=lab)
    by_cluster: dict[str, Any] = {}
    for cl, grp in work.groupby("_cluster"):
        if pd.isna(cl):
            continue
        key = f"cluster_{int(cl)}"
        members = sorted(grp["asset"].unique())
        cell: dict[str, Any] = {
            "n_trades": int(len(grp)),
            "members": [str(m) for m in members],
            "n_assets": len(members),
        }
        for m in PATH_METRICS:
            if m not in grp.columns:
                continue
            s = pd.to_numeric(grp[m], errors="coerce")
            cell[m] = {
                "median": float(s.median()) if s.notna().any() else None,
                "p25": _pct(s, 0.25),
                "p75": _pct(s, 0.75),
            }
        if "exit_u_ret" in grp.columns:
            cell["win_rate"] = float((pd.to_numeric(grp["exit_u_ret"], errors="coerce") > 0).mean())
        by_cluster[key] = cell
        E.LEDGER.count("cluster_path_link")
    out["by_cluster"] = by_cluster

    # pairwise asset trade-path similarity on standardized medians (§44)
    if "asset" in frame.columns:
        rows = []
        for asset, g in frame.groupby("asset"):
            if len(g) < C.MIN_CELL_TRADES:
                continue
            rec = {"asset": str(asset)}
            for m in (
                "first_profit_bar",
                "max_underwater_run",
                "mae_sigma",
                "mfe_sigma",
                "crossings_per_bar",
                "path_efficiency",
                "underwater_fraction",
            ):
                if m in g.columns:
                    s = pd.to_numeric(g[m], errors="coerce").dropna()
                    rec[m] = float(s.median()) if len(s) else np.nan
            rows.append(rec)
        if len(rows) >= 3:
            med = pd.DataFrame(rows).set_index("asset")
            z = (med - med.mean()) / med.std(ddof=1).replace(0, np.nan)
            z = z.fillna(0.0)
            a = z.to_numpy()
            diff = a[:, None, :] - a[None, :, :]
            d = np.sqrt((diff**2).sum(axis=-1))
            dist = pd.DataFrame(d, index=med.index, columns=med.index)
            # nearest trade-path neighbor per asset
            nn = {}
            for i, name in enumerate(med.index):
                row = dist.loc[name].drop(name)
                nn[str(name)] = {"nearest": str(row.idxmin()), "distance": float(row.min())}
            out["trade_path_distance"] = dist.to_dict()
            out["trade_path_nearest_neighbor"] = nn
            E.LEDGER.count("trade_path_pairwise_distances", int(len(med) * (len(med) - 1) // 2))
    return out


def holding_period_buckets(frame: pd.DataFrame) -> dict[str, Any]:
    """§36: oscillation within holding-period buckets (strategy horizon = weekly rebalance → mostly 6 bars)."""
    out: dict[str, Any] = {}
    if frame.empty or "holding_bars" not in frame.columns:
        return out
    hb = pd.to_numeric(frame["holding_bars"], errors="coerce")
    # buckets fixed: short <6, medium ==6 (modal weekly), long >6
    buckets = pd.Series(np.where(hb < 6, "short", np.where(hb > 6, "long", "medium")), index=frame.index)
    work = frame.assign(_hb=buckets)
    for b, grp in work.groupby("_hb"):
        cell: dict[str, Any] = {"n": int(len(grp))}
        if len(grp) < C.MIN_CELL_TRADES:
            cell["verdict"] = E.INSUFFICIENT_DATA
            out[str(b)] = cell
            continue
        for m in ("crossings_per_bar", "entry_crossings", "max_underwater_run", "first_profit_bar", "path_efficiency"):
            if m not in grp.columns:
                continue
            s = pd.to_numeric(grp[m], errors="coerce")
            cell[m] = {"median": float(s.median()) if s.notna().any() else None}
        if "entry_rv_pctile" in grp.columns:
            # re-check H1 direction inside bucket (descriptive)
            from research.volatility.evidence import spearman_with_p

            d = grp[["entry_rv_pctile", "max_underwater_run"]].dropna()
            if len(d) >= C.MIN_CELL_TRADES:
                rho, p = spearman_with_p(d["entry_rv_pctile"], d["max_underwater_run"])
                cell["h1_rho_within_bucket"] = {"rho": rho, "p": p, "n": int(len(d))}
                E.LEDGER.count("holding_bucket_h1")
        out[str(b)] = cell
    return out


def build_all_path_tables(frame: pd.DataFrame, cluster_labels: dict[str, int]) -> dict[str, Any]:
    """Assemble every report-facing trade-path table in one call."""
    return {
        "per_asset_trade_path": per_asset_trade_path_table(frame),
        "per_asset_regime": per_asset_regime_table(frame),
        "volatility_trade_path_matrix": volatility_trade_path_matrix(frame),
        "cost_analysis": cost_analysis(frame),
        "survival_time_to_event": survival_time_to_event(frame),
        "cluster_path_link": cluster_path_link(frame, cluster_labels),
        "holding_period_control": holding_period_buckets(frame),
    }
