"""End-to-end runner: taxonomy (Question A) + trade path (Question B).

Writes JSON artifacts under reports/volatility_taxonomy/:
  taxonomy_results.json        Question A structure, clusters, stability,
                               similarity, LOO, candidate insertion
  trade_path_results.json      Question B population, H1-H7, F1-F12,
                               regime-conditional tables
  evidence_ledger.json         every comparison counted; Holm families
  reproducibility.json         config version, git commit, manifest hashes,
                               file hashes, windows, params, package versions

Descriptive only. Never cites itself as authorization for production change.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.volatility import clustering as CL
from research.volatility import config as C
from research.volatility import data as DATA
from research.volatility import evidence as E
from research.volatility import features as F
from research.volatility import hypotheses as H
from research.volatility import incremental as INC
from research.volatility import path_tables as PT
from research.volatility import regimes as R
from research.volatility import similarity as SIM
from research.volatility import stability as ST
from research.volatility import trade_path as TP
from research.volatility import trade_stream as TS

OUT_DIR = C.REPO / "reports" / "volatility_taxonomy"


# ── JSON helpers ─────────────────────────────────────────────────────


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        return None if not math.isfinite(f) else f
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, pd.DataFrame):
        raise TypeError("DataFrames must be converted before dump")
    if obj is pd.NA or obj is pd.NaT:
        return None
    return obj


def _dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_jsonable(payload), indent=2, sort_keys=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, cwd=C.REPO).strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


# ── Question A: taxonomy ─────────────────────────────────────────────


def _windowed_series(
    df: pd.DataFrame, asset: str, cls: str, start: str, end: str, warmup: int = 60
) -> F.AssetVolSeries:
    """Build an AssetVolSeries with `warmup` bars before `start`, then clip
    all outputs to [start, end] so summaries share the declared window."""
    idx = df.index
    pos = int(idx.searchsorted(pd.Timestamp(start)))
    lo = max(0, pos - warmup)
    sub = df.iloc[lo:]
    sub = sub.loc[: pd.Timestamp(end)]
    a = F.build_asset_series(asset, cls, sub)
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return F.AssetVolSeries(
        instrument=a.instrument,
        asset_class=a.asset_class,
        bars=a.bars.loc[s:e],
        returns=a.returns.loc[s:e],
        rv={k: v.loc[s:e] for k, v in a.rv.items()},
        rv20=a.rv20.loc[s:e],
        pk20=a.pk20.loc[s:e],
        gk20=a.gk20.loc[s:e],
        atr14_pct=a.atr14_pct.loc[s:e],
        integrity=a.integrity,
    )


def _extreme_regime_freq(a: F.AssetVolSeries) -> float:
    labels = R.expanding_percentile_regimes(a.rv20)
    freqs = R.regime_frequencies(labels)
    return float(freqs.get("EXTREME", float("nan")))


def _build_features(summaries: dict[str, dict[str, float]]) -> pd.DataFrame:
    feats = CL.build_feature_matrix(summaries)
    for asset, s in summaries.items():
        feats.loc[asset, "f8_extreme_regime_freq"] = s.get("extreme_regime_freq", float("nan"))
    return feats


def _silhouette_table(features: pd.DataFrame) -> dict[str, float]:
    """Silhouette for each k in the frozen candidate set (average linkage)."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    scaled = CL.robust_scale(features)
    n = len(scaled)
    if n < 3:
        return {str(k): float("nan") for k in C.CLUSTER_K_CANDIDATES}
    condensed = pdist(scaled.to_numpy(dtype=float), metric="euclidean")
    Z = linkage(condensed, method="average")
    out: dict[str, float] = {}
    for k in C.CLUSTER_K_CANDIDATES:
        if k >= n:
            out[str(k)] = float("nan")
            continue
        lab = fcluster(Z, t=k, criterion="maxclust")
        try:
            out[str(k)] = float(CL.silhouette_score(scaled.to_numpy(dtype=float), lab, metric="euclidean"))
        except ValueError:
            out[str(k)] = float("nan")
    return out


def run_taxonomy(bundle: DATA.DatasetBundle) -> dict:
    """Question A — cross-asset volatility taxonomy of the 34-asset baseline."""
    result: dict[str, Any] = {}
    result["windows"] = {
        "primary": [C.PRIMARY_START, C.PRIMARY_END],
        "robustness_full": [C.FULL_START, C.FULL_END],
        "xng_note": "XNGUSD history starts 2022-03-20; robustness window excludes it",
    }
    result["integrity"] = DATA.integrity_report(bundle)

    # ── Per-asset measurement (primary window) ───────────────────────
    series: dict[str, F.AssetVolSeries] = {}
    summaries: dict[str, dict[str, float]] = {}
    for asset, df in bundle.baseline.items():
        cls = C.ASSET_CLASSES[asset]
        a = _windowed_series(df, asset, cls, C.PRIMARY_START, C.PRIMARY_END)
        series[asset] = a
        s = F.summarize_series(a)
        s["extreme_regime_freq"] = _extreme_regime_freq(a)
        s["asset_class"] = cls
        summaries[asset] = s
    result["asset_summaries"] = summaries

    # robustness window (33 assets, XNG excluded)
    robust_summaries: dict[str, dict[str, float]] = {}
    for asset, df in bundle.baseline.items():
        if asset == C.XNGUSD:
            continue
        a = _windowed_series(df, asset, C.ASSET_CLASSES[asset], C.FULL_START, C.FULL_END)
        s = F.summarize_series(a)
        s["extreme_regime_freq"] = _extreme_regime_freq(a)
        robust_summaries[asset] = s
    result["asset_summaries_robustness_full"] = robust_summaries

    # ── Feature matrix + primary clustering ──────────────────────────
    feats = _build_features(summaries)
    result["feature_matrix"] = feats.to_dict(orient="index")
    result["feature_columns"] = list(feats.columns)

    fit = CL.cluster_features(feats)
    result["primary_clustering"] = {
        "method": "average linkage, euclidean, robust-scaled 9 features",
        "k": int(fit.k),
        "silhouette": fit.silhouette,
        "labels": {a: int(v) for a, v in fit.labels.items()},
        "k_silhouette_table": _silhouette_table(feats),
    }
    E.LEDGER.clustering_configurations += 1

    # ── Declared sensitivities (counted) ─────────────────────────────
    sens: dict[str, Any] = {}
    ward = pd.Series(CL.ward_clusters(feats, fit.k), dtype=int)
    ward.index = feats.index
    sens["ward_k_primary"] = {
        "k": int(fit.k),
        "labels": {a: int(v) for a, v in ward.items()},
        "ari_vs_primary": ST.ari_vs_full(fit.labels, ward),
    }
    E.LEDGER.clustering_configurations += 1

    corr_lab = pd.Series(
        CL.corr_distance_clusters({a: s.rv20 for a, s in series.items()}, fit.k),
        dtype=int,
    )
    sens["correlation_distance_k_primary"] = {
        "k": int(fit.k),
        "labels": {a: int(v) for a, v in corr_lab.items()},
        "ari_vs_primary": ST.ari_vs_full(fit.labels, corr_lab),
    }
    E.LEDGER.clustering_configurations += 1

    km = pd.Series(CL.kmeans_pca_clusters(feats, fit.k, seed=C.RANDOM_SEED), dtype=int)
    km.index = feats.index
    sens["pca2_kmeans_k_primary"] = {
        "k": int(fit.k),
        "labels": {a: int(v) for a, v in km.items()},
        "ari_vs_primary": ST.ari_vs_full(fit.labels, km),
        "seed": C.RANDOM_SEED,
    }
    E.LEDGER.clustering_configurations += 1

    # PCA structure (90% threshold)
    _, evr = CL.pca_transform(feats)
    cum = np.cumsum(evr)
    n90 = int(np.searchsorted(cum, C.PCA_VAR_THRESHOLD) + 1) if len(cum) else 0
    pca = CL.pca_structure(feats)
    pca["n_components_90pct"] = n90
    pca["explained_ratio_cum"] = [float(x) for x in cum]
    sens["pca_structure"] = pca
    result["sensitivities"] = sens

    # ── Temporal stability ───────────────────────────────────────────
    # Chronological thirds of the union trading calendar in the window.
    union_idx = pd.DatetimeIndex(sorted(set().union(*[set(s.bars.index) for s in series.values()])))
    bounds = ST.subsample_bounds(union_idx, C.N_CHRONO_SUBSAMPLES)
    thirds_feats: dict[str, pd.DataFrame] = {}
    thirds_series: dict[str, dict[str, F.AssetVolSeries]] = {}
    for i, (b0, b1) in enumerate(bounds):
        name = ["early", "middle", "recent"][i]
        third_summ: dict[str, dict[str, float]] = {}
        thirds_series[name] = {}
        for asset, df in bundle.baseline.items():
            cls = C.ASSET_CLASSES[asset]
            a = _windowed_series(df, asset, cls, str(b0.date()), str(b1.date()), warmup=60)
            if len(a.bars) < 120:
                continue
            s = F.summarize_series(a)
            s["extreme_regime_freq"] = _extreme_regime_freq(a)
            third_summ[asset] = s
            thirds_series[name][asset] = a
        if len(third_summ) >= 4:
            thirds_feats[name] = _build_features(third_summ)

    stab = ST.stability_report(thirds_feats, fit.labels)
    if stab.get("stable"):
        stab["verdict"] = E.STABLE
    elif aris_ok(stab):
        stab["verdict"] = E.UNSTABLE
    else:
        stab["verdict"] = E.INCONCLUSIVE
    # distance stability early vs recent
    if "early" in thirds_feats and "recent" in thirds_feats:
        stab["distance_stability_early_vs_recent"] = ST.distance_stability(
            thirds_feats["early"], thirds_feats["recent"]
        )
    # rolling co-membership on the third windows
    stab["co_membership"] = ST.rolling_co_membership(list(thirds_feats.items()), fit.labels)
    stab["thirds_bounds"] = [[str(x[0].date()), str(x[1].date())] for x in bounds]
    result["temporal_stability"] = stab

    # ── Regime structure (descriptive, PIT expanding percentile) ─────
    regime_struct: dict[str, Any] = {}
    labels_panel: dict[str, pd.Series] = {}
    for asset, a in series.items():
        lab = R.expanding_percentile_regimes(a.rv20)
        labels_panel[asset] = lab
        regime_struct[asset] = {
            "freq": R.regime_frequencies(lab),
            "runs": R.regime_runs(lab),
            "transition": R.transition_matrix(lab).to_dict(),
        }
    result["regime_structure"] = regime_struct

    # ── Similarity ───────────────────────────────────────────────────
    rv_panel = pd.DataFrame({a: s.rv20 for a, s in series.items()})
    closes_panel = pd.DataFrame({a: s.bars["close"] for a, s in series.items()})
    regime_df = pd.DataFrame(labels_panel)

    sim = {
        "rv_corr": SIM.rv_correlations(rv_panel)["rv"].to_dict(),
        "log_rv_corr": SIM.rv_correlations(rv_panel)["log_rv"].to_dict(),
        "d_log_rv_corr": SIM.rv_correlations(rv_panel)["d_log_rv"].to_dict(),
        "abs_return_corr": SIM.abs_return_correlations(closes_panel).to_dict(),
        "return_corr_return_space": SIM.return_correlations(closes_panel).to_dict(),
        "return_corr_note": "RETURN-space, reported separately; never a volatility-similarity proxy",
        "regime_cooccurrence": {k: v.to_dict() for k, v in SIM.regime_cooccurrence(regime_df).items()},
        "feature_distance": SIM.feature_distance(feats).to_dict(),
    }
    # rolling log-RV correlation endpoints (declared descriptive statistic)
    roll = SIM.rolling_rv_corr(rv_panel)
    sim["rolling_log_rv_corr_endpoints"] = {k: v.to_dict() for k, v in roll.items()}
    result["similarity"] = sim
    E.LEDGER.count("similarity_matrices", 8)

    # pairwise feature distances counted as comparisons
    n_assets = len(feats)
    E.LEDGER.count("pairwise_feature_distances", n_assets * (n_assets - 1) // 2)
    E.LEDGER.count("pairwise_rv_correlations", n_assets * (n_assets - 1) // 2)

    # ── Leave-one-out ────────────────────────────────────────────────
    loo = INC.loo_report(feats)
    E.LEDGER.loo_evaluations += len(C.BASELINE_ASSETS)
    result["leave_one_out"] = loo

    # ── Candidate insertion (USOIL, COPPER) ──────────────────────────
    candidates: dict[str, Any] = {}
    for cand in C.CANDIDATE_ASSETS:
        if cand not in bundle.candidates:
            candidates[cand] = {"classification": E.INSUFFICIENT_DATA, "detail": "candidate data missing"}
            continue
        df = bundle.candidates[cand]
        a = _windowed_series(df, cand, C.CANDIDATE_ASSETS[cand], C.PRIMARY_START, C.PRIMARY_END)
        s = F.summarize_series(a)
        s["extreme_regime_freq"] = _extreme_regime_freq(a)
        cand_feats = _build_features({cand: s})
        rep = INC.candidate_report(feats, cand, cand_feats)
        candidates[cand] = rep
        E.LEDGER.candidate_evaluations += 1
    result["candidates"] = candidates

    # primary-window caveat: XNG short history
    result["coverage_caveats"] = list(bundle.load_warnings)
    return result


def aris_ok(stab: dict) -> bool:
    return "ari_min" in stab and np.isfinite(stab.get("ari_min", float("nan")))


# ── Question B: trade path ───────────────────────────────────────────


def _alt_entry_columns(trades: list[TS.PathTrade], bars_by_sym: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Alternative PIT entry-vol measures (F9 ATR-percentile, F10 z(log RV))."""
    rows = []
    cache: dict[str, dict] = {}
    for t in trades:
        sym = t.instrument
        if sym not in bars_by_sym:
            rows.append({"trade_id": t.trade_id, "alt_atr_pctile": np.nan, "alt_logrv_z": np.nan})
            continue
        if sym not in cache:
            df = bars_by_sym[sym]
            atr = F.atr_pct(df["high"], df["low"], df["close"], 14)
            atr_pctile = atr.expanding(min_periods=250).rank(pct=True)
            rv = F.realized_vol(df["close"], C.PRIMARY_RV)
            logrv = np.log(rv.replace(0.0, np.nan))
            mu = logrv.expanding(min_periods=250).mean()
            sd = logrv.expanding(min_periods=250).std(ddof=1)
            cache[sym] = {
                "atr_pctile": atr_pctile,
                "logrv_z": (logrv - mu) / sd.replace(0.0, np.nan),
            }
        c = cache[sym]
        entry = pd.Timestamp(t.entry_ts)
        prior_a = c["atr_pctile"].index[c["atr_pctile"].index < entry]
        prior_z = c["logrv_z"].index[c["logrv_z"].index < entry]
        av = c["atr_pctile"].loc[prior_a[-1]] if len(prior_a) else np.nan
        zv = c["logrv_z"].loc[prior_z[-1]] if len(prior_z) else np.nan
        rows.append(
            {
                "trade_id": t.trade_id,
                "alt_atr_pctile": float(av) if pd.notna(av) else np.nan,
                "alt_logrv_z": float(zv) if pd.notna(zv) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _regime_conditional_tables(frame: pd.DataFrame) -> dict:
    """Metric means by entry regime; cells below MIN_CELL → INSUFFICIENT DATA."""
    out: dict[str, Any] = {}
    metrics = [
        "max_underwater_run",
        "crossings_per_bar",
        "first_profit_bar",
        "time_to_mfe",
        "mae_ret",
        "mfe_ret",
        "path_efficiency",
        "underwater_fraction",
        "holding_bars",
    ]
    for col, name in (("entry_regime", "percentile_pit"), ("entry_regime_z", "zscore")):
        table: dict[str, Any] = {}
        for reg in C.REGIME_LABELS:
            sub = frame[frame[col] == reg]
            n = int(len(sub))
            if n < C.MIN_CELL_TRADES:
                table[reg] = {"n": n, "verdict": E.INSUFFICIENT_DATA}
                continue
            cell: dict[str, Any] = {"n": n}
            for m in metrics:
                vals = pd.to_numeric(sub[m], errors="coerce").dropna()
                cell[m] = {
                    "mean": float(vals.mean()) if len(vals) else None,
                    "median": float(vals.median()) if len(vals) else None,
                }
            cell["trade_types"] = sub["trade_type"].value_counts().to_dict()
            cell["win_rate"] = float((sub["exit_u_ret"] > 0).mean())
            table[reg] = cell
        # cross-regime comparison counter
        E.LEDGER.count(f"regime_cell_comparisons:{name}", len(C.REGIME_LABELS))
        out[name] = table
    return out


def run_trade_path() -> dict:
    """Question B — trade-path metrics, H1-H7, falsification battery."""
    result: dict[str, Any] = {}

    trades, prov = TS.replay_pit_population()
    result["population_provenance"] = prov

    m, params, bars_by_sym, _weights = TS.load_signal_and_data()
    frame, audit = TP.build_path_metrics(trades, bars_by_sym)
    result["path_metrics_audit"] = audit
    if frame.empty:
        result["verdict"] = E.INCONCLUSIVE
        result["detail"] = "no reconstructable trade paths"
        return result

    # numeric coercion for object columns
    for col in ("first_profit_bar", "time_to_mfe", "time_to_mae", "entry_rv_pctile", "time_to_large_favorable"):
        if col in frame:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

    # attach alternative entry-vol measures (F9/F10)
    alt = _alt_entry_columns(trades, bars_by_sym)
    frame = frame.merge(alt, on="trade_id", how="left")

    # ── H1-H4 pooled (Holm-corrected family) ────────────────────────
    h_pooled = H.evaluate_h1_h4_pooled(frame)
    h_within = H.evaluate_h_within_asset(frame)
    h5 = H.evaluate_h5_normalization(frame)
    h6 = H.evaluate_h6_periods(frame)
    h7 = H.evaluate_h7_holding(frame)

    # F9: ATR-percentile as entry-vol X; F10: expanding z(log RV) as X
    alt_atr_rhos: dict[str, float] = {}
    alt_z_rhos: dict[str, float] = {}
    for hyp, col in H.METRICS_NEG.items():
        d = frame[[col]].join(frame[["alt_atr_pctile"]]).dropna()
        if col == "first_profit_bar":
            d = d[d[col].notna()]
        r_a, _ = (
            E.spearman_with_p(d["alt_atr_pctile"], d[col])
            if len(d) >= C.MIN_CELL_TRADES
            else (float("nan"), float("nan"))
        )
        alt_atr_rhos[hyp] = r_a
        d2 = frame[[col]].join(frame[["alt_logrv_z"]]).dropna()
        if col == "first_profit_bar":
            d2 = d2[d2[col].notna()]
        r_z, _ = (
            E.spearman_with_p(d2["alt_logrv_z"], d2[col])
            if len(d2) >= C.MIN_CELL_TRADES
            else (float("nan"), float("nan"))
        )
        alt_z_rhos[hyp] = r_z
        E.LEDGER.count(f"alt_estimator_spearman:{hyp}", 2)

    battery = H.falsification_battery(
        frame,
        h_within,
        h5,
        h6,
        h7,
        alt_entry_vol_rhos=alt_atr_rhos,
        alt_regime_rhos=alt_z_rhos,
    )

    # ── Descriptive summaries ────────────────────────────────────────
    numeric = frame.select_dtypes(include=[np.number])
    result["metric_distributions"] = {
        col: {
            "mean": float(numeric[col].mean()),
            "median": float(numeric[col].median()),
            "p25": float(numeric[col].quantile(0.25)),
            "p75": float(numeric[col].quantile(0.75)),
        }
        for col in (
            "mae_ret",
            "mfe_ret",
            "mae_sigma",
            "mfe_sigma",
            "max_underwater_run",
            "underwater_fraction",
            "crossings_per_bar",
            "path_efficiency",
            "holding_bars",
            "net_pnl",
        )
        if col in numeric
    }
    result["trade_type_distribution"] = frame["trade_type"].value_counts().to_dict()
    result["side_distribution"] = frame["side"].value_counts().to_dict()
    result["asset_distribution"] = frame["asset"].value_counts().to_dict()
    result["no_profit_rate"] = float(frame["first_profit_bar"].isna().mean())
    result["large_move_rate"] = float(frame["large_favorable"].mean())
    result["delayed_expansion_rate"] = float(frame["delayed_expansion"].mean())

    # ── Regime-conditional tables (both regime constructions) ────────
    result["regime_conditional"] = _regime_conditional_tables(frame)

    # ── Report deliverable tables (§52–§54, §35–§37, §40, §44) ──────
    # cluster labels attached in run_all once taxonomy is available;
    # here we compute the path-only tables that do not need labels.
    result["path_tables_partial"] = {
        "cost_analysis": PT.cost_analysis(frame),
        "survival_time_to_event": PT.survival_time_to_event(frame),
        "holding_period_control": PT.holding_period_buckets(frame),
        "per_asset_trade_path": PT.per_asset_trade_path_table(frame),
        "per_asset_regime": PT.per_asset_regime_table(frame),
        "volatility_trade_path_matrix": PT.volatility_trade_path_matrix(frame),
    }

    # ── Hypotheses & falsification ───────────────────────────────────
    result["hypotheses"] = {
        "H1_H4_pooled": h_pooled,
        "within_asset": h_within,
        "H5_normalization": h5,
        "H6_periods": h6,
        "H7_holding_control": h7,
    }
    result["falsification_battery"] = battery
    result["alt_entry_vol_rhos"] = {"atr_percentile": alt_atr_rhos, "expanding_z_logrv": alt_z_rhos}

    # Overall verdict vocabulary for the low-vol trade-path hypothesis
    h1 = h_pooled.get("H1_underwater", {})
    fsum = battery.get("_battery_summary", {})
    if h1.get("verdict") == E.SUPPORTED and fsum.get("n_fails", 0) == 0:
        overall = E.SUPPORTED
    elif h1.get("verdict") == E.NOT_SUPPORTED or fsum.get("n_fails", 0) >= 3:
        overall = E.NOT_SUPPORTED
    else:
        overall = E.INCONCLUSIVE
    result["low_vol_trade_path_hypothesis"] = {
        "claim": "lower entry volatility => longer underwater / slower favorable resolution",
        "H1_verdict": h1.get("verdict"),
        "battery": fsum,
        "verdict": overall,
    }

    # ── Frozen-stream comparator (robustness only) ───────────────────
    try:
        fs = TS.load_frozen_stream()
        result["frozen_stream_comparator"] = {
            "stream_id": fs.stream_id,
            "n_trades": len(fs.trades),
            "note": "frozen exporter fills at open of signal date (documented "
            "lookahead defect); robustness comparator only",
        }
    except Exception as exc:
        result["frozen_stream_comparator"] = {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    # full per-trade metrics table (compact JSON rows)
    result["trade_path_rows"] = json.loads(frame.to_json(orient="records", date_format="iso"))
    return result


# ── Reproducibility + main ───────────────────────────────────────────


def reproducibility_record(bundle: DATA.DatasetBundle) -> dict:
    import hashlib

    file_hashes = {}
    pkg = Path(__file__).resolve().parent
    for f in sorted(pkg.glob("*.py")):
        file_hashes[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()

    try:
        import scipy
        import sklearn

        versions = {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
        }
    except ImportError:
        versions = {"python": sys.version.split()[0]}

    return {
        "config_version": C.CONFIG_VERSION,
        "git_commit": _git_commit(),
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "manifest_hashes": bundle.manifest_hashes,
        "package_file_sha256": file_hashes,
        "windows": {
            "primary": [C.PRIMARY_START, C.PRIMARY_END],
            "robustness_full": [C.FULL_START, C.FULL_END],
        },
        "constants": {
            "primary_rv": C.PRIMARY_RV,
            "annualization": C.ANNUALIZATION,
            "regime_cuts_pctile": list(C.REGIME_CUTS_PCTILE),
            "regime_cuts_z": list(C.REGIME_CUTS_Z),
            "cluster_k_candidates": list(C.CLUSTER_K_CANDIDATES),
            "primary_linkage": C.PRIMARY_LINKAGE,
            "primary_distance": C.PRIMARY_DISTANCE,
            "large_move_k_sigma": C.LARGE_MOVE_K_SIGMA,
            "initial_phase_bars": C.INITIAL_PHASE_BARS,
            "min_cell_trades": C.MIN_CELL_TRADES,
            "random_seed": C.RANDOM_SEED,
            "r4_cost_one_way": C.R4_COST_ONE_WAY,
            "r4_rebalance_every": C.R4_REBALANCE_EVERY,
        },
        "h_families": C.H_FAMILIES,
        "versions": versions,
        "trade_symbols": C.TRADE_SYMBOLS,
        "baseline_assets": C.BASELINE_ASSETS,
        "candidates": C.CANDIDATE_ASSETS,
        "governance": (
            "descriptive/diagnostic only; no trial slot, no experiment registration, no production authorization"
        ),
    }


def run_all(write: bool = True) -> dict:
    bundle = DATA.load_dataset(verify=True)
    taxonomy = run_taxonomy(bundle)
    trade_path = run_trade_path()

    # Attach cluster↔trade-path link and path similarity (needs both sides).
    if "trade_path_rows" in trade_path and taxonomy.get("primary_clustering"):
        try:
            frame = pd.DataFrame(trade_path["trade_path_rows"])
            labels = taxonomy["primary_clustering"].get("labels", {})
            trade_path["cluster_path_link"] = PT.cluster_path_link(frame, labels)
        except Exception as exc:
            trade_path["cluster_path_link"] = {"error": f"{type(exc).__name__}: {exc}"}

    # Asset-specific volatility digests (§14) from taxonomy summaries.
    taxonomy["asset_specific"] = _asset_specific_digest(taxonomy)

    ledger = E.LEDGER.to_dict()
    repro = reproducibility_record(bundle)

    out = {
        "taxonomy": taxonomy,
        "trade_path": trade_path,
        "ledger": ledger,
        "reproducibility": repro,
    }
    if write:
        _dump(OUT_DIR / "taxonomy_results.json", taxonomy)
        _dump(OUT_DIR / "trade_path_results.json", trade_path)
        _dump(OUT_DIR / "evidence_ledger.json", ledger)
        _dump(OUT_DIR / "reproducibility.json", repro)
    return out


def _asset_specific_digest(taxonomy: dict) -> dict:
    """§14: focused descriptive digests for named assets/families."""
    summ = taxonomy.get("asset_summaries", {})
    labels = taxonomy.get("primary_clustering", {}).get("labels", {})
    regime = taxonomy.get("regime_structure", {})
    sim = taxonomy.get("similarity", {})

    def _one(asset: str) -> dict:
        s = summ.get(asset, {})
        reg = regime.get(asset, {})
        return {
            "mean_rv20": s.get("mean_rv20"),
            "rv20_cv": s.get("rv20_cv"),
            "rv_ac_lag1": s.get("rv_ac_lag1"),
            "absret_ac_lag1": s.get("absret_ac_lag1"),
            "excess_kurtosis": s.get("excess_kurtosis"),
            "extreme_freq_3sigma": s.get("extreme_freq_3sigma"),
            "jump_freq": s.get("jump_freq"),
            "rv_spike_freq": s.get("rv_spike_freq"),
            "skew": s.get("skew"),
            "q01": s.get("q01"),
            "q99": s.get("q99"),
            "estimator_dispersion": s.get("estimator_dispersion"),
            "cluster": labels.get(asset),
            "regime_freq": reg.get("freq"),
            "extreme_run_mean": (reg.get("runs") or {}).get("EXTREME", {}).get("mean_duration"),
        }

    out: dict = {}
    for a in ("BTCUSD", "XNGUSD", "XAUUSD", "XAGUSD", "US30", "USTEC"):
        out[a] = _one(a)

    # JPY crosses family coherence
    jpy = [a for a in summ if a.endswith("JPY")]
    jpy_clusters = {a: labels.get(a) for a in jpy}
    out["jpy_crosses"] = {
        "members": sorted(jpy),
        "clusters": jpy_clusters,
        "mean_rv20": {a: summ[a].get("mean_rv20") for a in sorted(jpy)},
        "all_same_cluster": len(set(jpy_clusters.values())) == 1 if jpy_clusters else None,
    }

    # pairwise notes of interest
    def _pair_corr(a: str, b: str) -> dict:
        r = {}
        for key in ("rv_corr", "log_rv_corr", "abs_return_corr", "return_corr_return_space"):
            mat = sim.get(key)
            if isinstance(mat, dict) and a in mat and b in mat[a]:
                r[key] = mat[a][b]
        return r

    out["pairs"] = {
        "XAUUSD_XAGUSD": _pair_corr("XAUUSD", "XAGUSD"),
        "US30_USTEC": _pair_corr("US30", "USTEC"),
        "BTCUSD_XNGUSD": _pair_corr("BTCUSD", "XNGUSD"),
        "XAUUSD_US30": _pair_corr("XAUUSD", "US30"),
    }
    # XAG cluster membership vs industrial-ish neighbors
    out["xag_cluster"] = labels.get("XAGUSD")
    out["xau_cluster"] = labels.get("XAUUSD")
    return out


if __name__ == "__main__":
    res = run_all(write=True)
    tp = res["trade_path"].get("low_vol_trade_path_hypothesis", {})
    print(f"taxonomy assets: {len(res['taxonomy'].get('feature_matrix', {}))}")
    print(f"trade-path verdict: {tp.get('verdict')}")
    print(f"comparisons counted: {res['ledger'].get('total_comparisons')}")
    print(f"artifacts written to {OUT_DIR}")
