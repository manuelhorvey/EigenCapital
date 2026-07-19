"""Phase 16 — Trade Quality Clustering.

Groups trades by common characteristics using K-means clustering:
  - Duration (candles)
  - MAE (R)
  - MFE (R)
  - Volatility at entry (ATR %)
  - Session (encoded)
  - Confidence (p_long)
  - Efficiency
  - Holding period

Identifies profitable clusters and their signatures.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np
from pathlib import Path

logger = logging.getLogger("eigencapital.audit.phase16_clustering")

SESSION_ENCODE = {
    "sydney": 0, "tokyo": 1, "london": 2, "new_york": 3,
    "sydney_tokyo": 4, "tokyo_london": 5, "london_ny": 6, "ny_close": 7,
    "off_hours": 8, "unknown": 9,
}

SIDE_ENCODE = {"BUY": 0, "SELL": 1}


def run(trades_map: dict[str, list[dict]]) -> dict[str, Any]:
    logger.info("Phase 16: Trade quality clustering")

    # Feature extraction
    features: list[list[float]] = []
    raw_trades: list[dict] = []
    asset_labels: list[str] = []

    for asset, trades in trades_map.items():
        for t in trades:
            prices = t.get("prices", [])
            duration = len(prices) if hasattr(prices, "__len__") else 1
            session_enc = SESSION_ENCODE.get(t.get("entry_session", "unknown"), 9)
            side_enc = SIDE_ENCODE.get(t.get("side", "BUY"), 0)

            features.append([
                float(duration),
                float(t.get("mae_r", 0)),
                float(t.get("mfe_r", 0)),
                min(float(t.get("atr_pct_entry", 0.01)), 0.05),  # cap ATR
                float(session_enc),
                float(t.get("prob_long", 0.5)),
                float(t.get("efficiency_score", 0)),
            ])
            raw_trades.append(t)
            asset_labels.append(asset)

    if len(features) < 20:
        return {"error": f"too few trades for clustering: {len(features)}"}

    X = np.array(features)
    # Normalize
    X_mean = X.mean(axis=0)
    X_std = X.std(axis=0)
    X_std[X_std == 0] = 1.0
    X_norm = (X - X_mean) / X_std

    # Elbow method silhouette scores for k=2..8
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    best_k = 3
    best_score = -1
    scores = []

    for k in range(2, min(9, len(features) // 5 + 1)):
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X_norm)
        if len(set(labels)) > 1:
            sc = silhouette_score(X_norm, labels)
            scores.append({"k": k, "silhouette": round(float(sc), 4)})
            if sc > best_score:
                best_score = sc
                best_k = k

    # Final clustering with best_k
    km = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    cluster_labels = km.fit_predict(X_norm)

    # Profile each cluster
    clusters: dict[int, dict] = {}
    for cluster_id in range(best_k):
        indices = np.where(cluster_labels == cluster_id)[0]
        cluster_rs = np.array([raw_trades[i]["r_multiple"] for i in indices])
        cluster_trades = [raw_trades[i] for i in indices]

        mean_feats = X[indices].mean(axis=0)
        clusters[int(cluster_id)] = {
            "n_trades": len(indices),
            "pct_of_total": round(len(indices) / len(features) * 100, 1),
            "total_r": round(float(cluster_rs.sum()), 2),
            "avg_r": round(float(cluster_rs.mean()), 4),
            "median_r": round(float(np.median(cluster_rs)), 4),
            "win_rate": round((cluster_rs > 0).mean() * 100, 1),
            "sharpe": round(float(cluster_rs.mean() / cluster_rs.std()), 4) if cluster_rs.std() > 0 else 0.0,
            "profile": {
                "avg_duration": round(float(mean_feats[0]), 1),
                "avg_mae_r": round(float(mean_feats[1]), 4),
                "avg_mfe_r": round(float(mean_feats[2]), 4),
                "avg_atr_pct": round(float(mean_feats[3]), 4),
                "session": str(int(round(mean_feats[4]))),
                "avg_confidence": round(float(mean_feats[5]), 4),
                "avg_efficiency": round(float(mean_feats[6]), 4),
            },
            "top_assets": sorted(
                [(a, raw_trades[i]["r_multiple"]) for i, a in enumerate([asset_labels[i] for i in indices])],
                key=lambda x: abs(x[1]), reverse=True
            )[:5],
        }

    return {
        "best_k": best_k,
        "silhouette_scores": scores,
        "n_features": X.shape[1],
        "feature_names": ["duration", "mae_r", "mfe_r", "atr_pct", "session_enc", "confidence", "efficiency"],
        "clusters": clusters,
        "cluster_summary": {
            k: {
                "n": v["n_trades"],
                "total_r": v["total_r"],
                "wr": v["win_rate"],
                "avg_r": v["avg_r"],
            }
            for k, v in sorted(clusters.items(), key=lambda x: x[1]["total_r"], reverse=True)
        },
    }
