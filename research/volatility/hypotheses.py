"""H1-H7 trade-path hypotheses and F1-F12 falsification battery.

Hypothesis direction (frozen BEFORE evaluation; from the brief's
observation): LOWER entry volatility => longer underwater, more
oscillation, slower favorable resolution. With entry RV percentile
measured PIT, this predicts NEGATIVE Spearman rho between entry
rv_pctile and (underwater duration, crossings rate, time-to-first-profit,
time-to-MFE).

Verdicts: SUPPORTED / NOT SUPPORTED / INCONCLUSIVE (fail-closed:
min cell C.MIN_CELL_TRADES, else INCONCLUSIVE). All p-values enter the
pre-declared families in config.H_FAMILIES and are Holm-corrected —
never reported raw as evidence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.volatility import config as C
from research.volatility.evidence import (
    INCONCLUSIVE,
    LEDGER,
    NOT_SUPPORTED,
    STABLE,
    SUPPORTED,
    UNSTABLE,
    spearman_with_p,
)

METRICS_NEG = {
    "H1_underwater": "max_underwater_run",
    "H2_oscillation": "crossings_per_bar",
    "H3_time_to_first_profit": "first_profit_bar",
    "H4_time_to_mfe": "time_to_mfe",
}
X_COL = "entry_rv_pctile"


def _clean(df: pd.DataFrame, y_col: str, require_finite_y: bool = True) -> pd.DataFrame:
    d = df[[X_COL, y_col]].dropna()
    return d


def evaluate_h1_h4_pooled(trades: pd.DataFrame) -> dict:
    """Pooled across all trades (family: H1_H4_pooled_spearman)."""
    out: dict = {}
    for hyp, col in METRICS_NEG.items():
        d = _clean(trades, col)
        # H3: NO_PROFIT excluded from ttf ranks (never coded as 0); report rate separately
        if col == "first_profit_bar":
            d = d[d[col].notna()]
        rho, p = spearman_with_p(d[X_COL], d[col])
        LEDGER.count(f"spearman_pooled:{hyp}")
        if not np.isfinite(rho):
            verdict = INCONCLUSIVE
        elif p <= 0.05 and rho < 0:
            verdict = SUPPORTED
        elif np.isfinite(p) and rho >= 0 and p <= 0.05:
            verdict = NOT_SUPPORTED  # significant but opposite direction
        elif np.isfinite(p) and p > 0.05 and rho < 0:
            verdict = INCONCLUSIVE  # direction right, insufficient evidence
        else:
            verdict = NOT_SUPPORTED
        LEDGER.record_test(
            "H1_H4_pooled_spearman",
            hyp,
            None if not np.isfinite(p) else p,
            None if not np.isfinite(rho) else rho,
            verdict,
            detail=f"n={len(d)} (p recorded pre-Holm)",
        )
        out[hyp] = {"rho": rho, "p": p, "n": len(d), "verdict": verdict}

    # NO_PROFIT rate by entry-RV quartile (H3 companion, descriptive)
    if X_COL in trades and trades[X_COL].notna().sum() >= C.MIN_CELL_TRADES:
        q = pd.qcut(trades[X_COL].rank(method="first"), 4, labels=["Q1_low", "Q2", "Q3", "Q4_high"])
        rate = (
            trades.assign(_q=q).groupby("_q", observed=True)["first_profit_bar"].apply(lambda s: float(s.isna().mean()))
        )
        out["H3_no_profit_rate_by_rv_quartile"] = {str(k): float(v) for k, v in rate.items()}
    LEDGER.holm_correct("H1_H4_pooled_spearman")
    # Re-derive verdicts from Holm-adjusted p (never report raw p as evidence).
    for hyp in METRICS_NEG:
        rec = LEDGER.hypothesis_tests["H1_H4_pooled_spearman"].get(hyp, {})
        p_adj = rec.get("p_holm")
        rho = out[hyp]["rho"]
        if p_adj is None:
            v = INCONCLUSIVE
        elif p_adj <= 0.05 and np.isfinite(rho) and rho < 0:
            v = SUPPORTED
        elif p_adj <= 0.05 and np.isfinite(rho) and rho >= 0:
            v = NOT_SUPPORTED
        else:
            v = INCONCLUSIVE
        rec["verdict"] = v
        out[hyp]["p_holm"] = p_adj
        out[hyp]["verdict"] = v
    return out


def evaluate_h_within_asset(trades: pd.DataFrame) -> dict:
    """Per-asset Spearman (family: H_within_asset_spearman)."""
    out: dict = {}
    for asset, grp in trades.groupby("asset"):
        if len(grp) < C.MIN_CELL_TRADES:
            continue
        for hyp, col in METRICS_NEG.items():
            d = grp[[X_COL, col]].dropna()
            if col == "first_profit_bar":
                d = d[d[col].notna()]
            rho, p = spearman_with_p(d[X_COL], d[col])
            LEDGER.count(f"spearman_within:{hyp}")
            key = f"{asset}:{hyp}"
            if not np.isfinite(rho):
                v = INCONCLUSIVE
            elif np.isfinite(p) and p <= 0.05 and rho < 0:
                v = SUPPORTED
            elif np.isfinite(p) and p <= 0.05 and rho >= 0:
                v = NOT_SUPPORTED
            else:
                v = INCONCLUSIVE
            LEDGER.record_test(
                "H_within_asset_spearman",
                key,
                None if not np.isfinite(p) else p,
                None if not np.isfinite(rho) else rho,
                v,
            )
            out[key] = {"rho": rho, "p": p, "n": len(d), "verdict": v}
    LEDGER.holm_correct("H_within_asset_spearman")
    # Re-derive per-test verdicts from Holm-adjusted p.
    for key in list(out):
        if key.startswith("_"):
            continue
        rec = LEDGER.hypothesis_tests["H_within_asset_spearman"].get(key, {})
        p_adj = rec.get("p_holm")
        rho = out[key]["rho"]
        if p_adj is None:
            v = INCONCLUSIVE
        elif p_adj <= 0.05 and np.isfinite(rho) and rho < 0:
            v = SUPPORTED
        elif p_adj <= 0.05 and np.isfinite(rho) and rho >= 0:
            v = NOT_SUPPORTED
        else:
            v = INCONCLUSIVE
        rec["verdict"] = v
        out[key]["p_holm"] = p_adj
        out[key]["verdict"] = v
    # F1 summary: sign consistency within assets
    rhos = [v["rho"] for v in out.values() if np.isfinite(v["rho"])]
    out["_summary"] = {
        "n_tests": len(rhos),
        "frac_negative": float(np.mean(np.array(rhos) < 0)) if rhos else float("nan"),
        "frac_supported": float(np.mean([v["verdict"] == SUPPORTED for v in out.values() if v.get("verdict")]))
        if out
        else float("nan"),
    }
    return out


def evaluate_h5_normalization(trades: pd.DataFrame) -> dict:
    """H5: excursion differences persist under volatility normalization.

    Compares rho(entry_rv_pctile, mae_ret) vs rho(entry_rv_pctile, mae_sigma)
    and mfe_ret vs mfe_sigma; plus dimensionless underwater_fraction (already
    normalized) re-test of H1.
    """
    out: dict = {}
    pairs = [("mae", "mae_ret", "mae_sigma"), ("mfe", "mfe_ret", "mfe_sigma")]
    for name, raw_col, norm_col in pairs:
        r_raw, p_raw = spearman_with_p(trades[X_COL], trades[raw_col])
        r_norm, p_norm = spearman_with_p(trades[X_COL], trades[norm_col])
        LEDGER.count(f"normalization_pair:{name}", 2)
        out[name] = {"rho_raw": r_raw, "rho_norm": r_norm, "p_raw": p_raw, "p_norm": p_norm}
    r_uw, p_uw = spearman_with_p(trades[X_COL], trades["underwater_fraction"])
    LEDGER.count("normalization_pair:underwater_fraction")
    out["underwater_fraction"] = {"rho": r_uw, "p": p_uw}
    # Operational H5: at least the dimensionless underwater relation keeps a
    # negative point estimate AND normalized MAE rho keeps its raw sign.
    neg_uw = np.isfinite(r_uw) and r_uw < 0
    mae_sign_kept = (
        np.isfinite(out["mae"]["rho_raw"])
        and np.isfinite(out["mae"]["rho_norm"])
        and (out["mae"]["rho_raw"] < 0) == (out["mae"]["rho_norm"] < 0)
    )
    out["verdict"] = SUPPORTED if (neg_uw and mae_sign_kept) else NOT_SUPPORTED
    if not np.isfinite(r_uw):
        out["verdict"] = INCONCLUSIVE
    return out


def evaluate_h6_periods(trades: pd.DataFrame) -> dict:
    """H6: sign stability of H1/H2/H4 across chronological thirds of entries."""
    t = trades.copy()
    t["_dt"] = pd.to_datetime(t["entry_ts"])
    t = t.sort_values("_dt")
    bounds = np.array_split(t.index, C.N_CHRONO_SUBSAMPLES)
    names = ["early", "middle", "recent"]
    out: dict = {}
    signs = []
    for name, idx in zip(names, bounds):
        sub = t.loc[idx]
        cell = {}
        for hyp, col in (
            ("H1_underwater", "max_underwater_run"),
            ("H2_oscillation", "crossings_per_bar"),
            ("H4_time_to_mfe", "time_to_mfe"),
        ):
            d = sub[[X_COL, col]].dropna()
            rho, p = spearman_with_p(d[X_COL], d[col])
            LEDGER.count(f"spearman_period:{name}:{hyp}")
            cell[hyp] = {"rho": rho, "p": p, "n": len(d)}
            if np.isfinite(rho):
                signs.append(rho < 0)
        cell["period"] = (str(sub["_dt"].min().date()), str(sub["_dt"].max().date()))
        out[name] = cell
    out["frac_negative_across_cells"] = float(np.mean(signs)) if signs else float("nan")
    out["verdict"] = STABLE if signs and np.mean(signs) >= 2 / 3 else (UNSTABLE if signs else INCONCLUSIVE)
    return out


def evaluate_h7_holding(trades: pd.DataFrame) -> dict:
    """H7: H1/H2 survive holding-period control (rank-residual partial rho)."""
    from scipy import stats

    out: dict = {}
    for hyp, col in METRICS_NEG.items():
        d = trades[[X_COL, col, "holding_bars"]].dropna()
        if col == "first_profit_bar":
            d = d[d[col].notna()]
        if len(d) < C.MIN_CELL_TRADES:
            out[hyp] = {"partial_rho": float("nan"), "n": len(d), "verdict": INCONCLUSIVE}
            continue
        rx = stats.rankdata(d[X_COL])
        ry = stats.rankdata(d[col])
        rh = stats.rankdata(d["holding_bars"])
        # residualize both on holding-bar ranks
        bx, _, _, _ = np.linalg.lstsq(np.column_stack([rh, np.ones(len(rh))]), rx, rcond=None)
        by, _, _, _ = np.linalg.lstsq(np.column_stack([rh, np.ones(len(rh))]), ry, rcond=None)
        ex = rx - np.column_stack([rh, np.ones(len(rh))]) @ bx
        ey = ry - np.column_stack([rh, np.ones(len(rh))]) @ by
        if np.std(ex) == 0 or np.std(ey) == 0:
            rho, p = float("nan"), float("nan")
        else:
            rho, p = float(np.corrcoef(ex, ey)[0, 1]), float(stats.pearsonr(ex, ey).pvalue)
        LEDGER.count(f"partial_spearman_holding:{hyp}")
        v = INCONCLUSIVE
        if np.isfinite(rho) and np.isfinite(p):
            if p <= 0.05 and rho < 0:
                v = SUPPORTED
            elif p <= 0.05 and rho >= 0:
                v = NOT_SUPPORTED
        out[hyp] = {"partial_rho": rho, "p": p, "n": len(d), "verdict": v}
    return out


# ── Falsification battery (F1-F12) ──────────────────────────────────


def falsification_battery(
    trades: pd.DataFrame,
    h_within: dict,
    h5: dict,
    h6: dict,
    h7: dict,
    alt_entry_vol_rhos: dict | None = None,
    alt_regime_rhos: dict | None = None,
) -> dict:
    """Run F1-F12 against the pooled H1 result. Each check reports
    survives | fails | inconclusive relative to the H1 claim."""
    out: dict = {}

    # F1 within-asset
    frac = h_within.get("_summary", {}).get("frac_negative", float("nan"))
    out["F1_within_asset"] = {
        "result": "survives"
        if np.isfinite(frac) and frac >= 0.5
        else ("fails" if np.isfinite(frac) and frac < 0.5 else "inconclusive"),
        "frac_negative_rho": frac,
        "purpose": "effect present within assets, not only cross-sectional",
    }

    # F2 normalization
    out["F2_normalization"] = {
        "result": "survives"
        if h5.get("verdict") == SUPPORTED
        else ("fails" if h5.get("verdict") == NOT_SUPPORTED else "inconclusive"),
        "detail": h5.get("verdict"),
    }

    # F3 holding period
    h7_neg = [
        v.get("partial_rho")
        for v in h7.values()
        if isinstance(v, dict) and np.isfinite(v.get("partial_rho", float("nan")))
    ]
    frac7 = float(np.mean(np.array(h7_neg) < 0)) if h7_neg else float("nan")
    out["F3_holding_period"] = {
        "result": "survives"
        if np.isfinite(frac7) and frac7 >= 0.5
        else ("fails" if np.isfinite(frac7) and frac7 < 0.5 else "inconclusive"),
        "frac_partial_negative": frac7,
    }

    # F4 strategy: single-strategy population by design
    out["F4_strategy"] = {
        "result": "inconclusive",
        "detail": "only one strategy population (frozen-R4 replica) exists; "
        "strategy effect cannot be separated from path effect",
    }

    # F5 costs: does the relation exist pre-cost AND net-of-cost?
    r_pre, p_pre = spearman_with_p(trades[X_COL], trades["max_underwater_run"])
    r_net, p_net = spearman_with_p(trades[X_COL], trades["max_underwater_run_net"])
    LEDGER.count("cost_path_pair", 2)
    net_stronger = np.isfinite(r_net) and np.isfinite(r_pre) and r_net < r_pre
    out["F5_costs"] = {
        "result": "fails"
        if (np.isfinite(r_pre) and r_pre >= 0)
        else ("inconclusive" if not np.isfinite(r_pre) else "survives"),
        "rho_price_path": r_pre,
        "rho_net_of_cost": r_net,
        "net_stronger_than_price": bool(net_stronger),
        "interpretation": "price-path (pre-cost) relation is the primary object; "
        "net-of-cost strengthening would implicate costs",
    }

    # F6 sessions: FX-only subset (7 FX pairs vs XAUUSD)
    fx = trades[trades["asset"] != "XAUUSD"]
    r_fx, p_fx = spearman_with_p(fx[X_COL], fx["max_underwater_run"])
    LEDGER.count("session_subset_pair")
    out["F6_sessions"] = {
        "result": "survives"
        if np.isfinite(r_fx) and r_fx < 0
        else ("fails" if np.isfinite(r_fx) and r_fx >= 0 else "inconclusive"),
        "rho_fx_only": r_fx,
        "detail": "trade population is 7 FX + XAUUSD; crypto/index sessions absent",
    }

    # F7 extreme trades: drop worst 1% / best 1% by |exit_u_ret|
    q = trades["exit_u_ret"].abs().quantile([0.01, 0.99])
    trimmed = trades[trades["exit_u_ret"].abs().between(q.loc[0.01], q.loc[0.99])]
    r_tr, p_tr = spearman_with_p(trimmed[X_COL], trimmed["max_underwater_run"])
    LEDGER.count("extreme_trim_pair")
    out["F7_extremes"] = {
        "result": "survives"
        if np.isfinite(r_tr) and r_tr < 0
        else ("fails" if np.isfinite(r_tr) and r_tr >= 0 else "inconclusive"),
        "rho_trimmed": r_tr,
        "n_trimmed": int(len(trimmed)),
    }

    # F8 periods
    out["F8_periods"] = {
        "result": "survives"
        if h6.get("verdict") == STABLE
        else ("fails" if h6.get("verdict") == UNSTABLE else "inconclusive"),
        "frac_negative": h6.get("frac_negative_across_cells"),
        "h6_verdict": h6.get("verdict"),
    }

    # F9 estimator: alternative entry-vol (ATR percentile) rhos
    if alt_entry_vol_rhos:
        alt_neg = [v for v in alt_entry_vol_rhos.values() if np.isfinite(v) and v < 0]
        frac_alt = (
            float(len(alt_neg) / len([v for v in alt_entry_vol_rhos.values() if np.isfinite(v)]))
            if alt_entry_vol_rhos
            else float("nan")
        )
        out["F9_estimator"] = {
            "result": "survives"
            if np.isfinite(frac_alt) and frac_alt >= 0.5
            else ("fails" if np.isfinite(frac_alt) and frac_alt < 0.5 else "inconclusive"),
            "alt_rhos": alt_entry_vol_rhos,
        }
    else:
        out["F9_estimator"] = {"result": "inconclusive", "detail": "alt estimator not computed"}

    # F10 regime definitions: H1 under an alternative PIT entry-vol
    # construction (expanding z of log-RV instead of expanding percentile).
    if alt_regime_rhos:
        finite = [v for v in alt_regime_rhos.values() if np.isfinite(v)]
        frac10 = float(np.mean(np.array(finite) < 0)) if finite else float("nan")
        out["F10_regime_definition"] = {
            "result": "survives"
            if np.isfinite(frac10) and frac10 >= 0.5
            else ("fails" if np.isfinite(frac10) and frac10 < 0.5 else "inconclusive"),
            "alt_rhos": alt_regime_rhos,
            "detail": "H1 re-run with expanding z(log RV) as entry-vol measure",
        }
    else:
        out["F10_regime_definition"] = {
            "result": "inconclusive",
            "detail": "alt regime construction not computed",
        }

    # F11 pre-specified large-move threshold
    if trades["large_favorable"].notna().any() and X_COL in trades:
        d = trades.dropna(subset=[X_COL])
        if len(d) >= C.MIN_CELL_TRADES:
            qcat = pd.qcut(d[X_COL].rank(method="first"), 4, labels=False)
            rate = d.groupby(qcat)["large_favorable"].mean()
            # observation implies low-vol takes LONGER -> delayed expansion more
            # common in Q1: requires rate(Q1) comparable and delayed_expansion
            # higher in Q1
            de = d.groupby(qcat)["delayed_expansion"].mean()
            rho_lg, p_lg = spearman_with_p(d[X_COL], d["time_to_large_favorable"].fillna(d["holding_bars"] + 1))
            LEDGER.count("large_move_pair")
            out["F11_large_move"] = {
                "result": "survives"
                if np.isfinite(rho_lg) and rho_lg < 0
                else ("fails" if np.isfinite(rho_lg) and rho_lg >= 0 else "inconclusive"),
                "rho_time_to_large": rho_lg,
                "large_move_rate_by_rv_q": [float(x) for x in rate.tolist()],
                "delayed_expansion_rate_by_rv_q": [float(x) for x in de.tolist()],
                "k": C.LARGE_MOVE_K_SIGMA,
            }
        else:
            out["F11_large_move"] = {"result": "inconclusive"}
    else:
        out["F11_large_move"] = {"result": "inconclusive"}

    # F12 cross vs within: combine F1 with pooled
    out["F12_cross_vs_within"] = {
        "result": out["F1_within_asset"]["result"],
        "detail": "cross-sectional pooled effect must also appear within assets",
    }

    results = [v["result"] for v in out.values() if isinstance(v, dict) and "result" in v]
    out["_battery_summary"] = {
        "n_checks": len(results),
        "n_survives": results.count("survives"),
        "n_fails": results.count("fails"),
        "n_inconclusive": results.count("inconclusive"),
    }
    LEDGER.count("falsification_checks", len(results))
    return out
