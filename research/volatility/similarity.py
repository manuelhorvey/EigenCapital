"""Volatility-space similarity (NOT return correlation).

Produces the matrices required by brief §15/§44:
  - corr(RV), corr(log RV), corr(|ret|), corr(delta log RV)
  - regime co-occurrence (joint HIGH/EXTREME frequency, Jaccard)
  - feature-space distance (euclidean on z-scored feature vectors)
Return correlation is computed separately and explicitly labeled as
return-space, never used as a volatility-similarity proxy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.volatility import features as F


def _corr(mat: pd.DataFrame) -> pd.DataFrame:
    return mat.corr(method="pearson")


def rv_correlations(rv: pd.DataFrame) -> dict[str, pd.DataFrame]:
    log_rv = np.log(rv.where(rv > 0))
    dlog = log_rv.diff()
    return {
        "rv": _corr(rv),
        "log_rv": _corr(log_rv),
        "d_log_rv": _corr(dlog),
    }


def abs_return_correlations(closes: pd.DataFrame) -> pd.DataFrame:
    return _corr(F.abs_returns_panel(closes))


def return_correlations(closes: pd.DataFrame) -> pd.DataFrame:
    """RETURN-space correlation — reported separately by contract."""
    return _corr(F.returns_panel(closes))


def regime_cooccurrence(regimes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """regimes: DataFrame of regime label strings (columns = assets).

    Returns:
      joint_high: P(both in HIGH|EXTREME)
      jaccard_high: |A∩B| / |A∪B| over HIGH|EXTREME indicator sets
      joint_extreme: P(both EXTREME)
    """
    high = regimes.isin(["HIGH", "EXTREME"]).astype(float)
    ext = (regimes == "EXTREME").astype(float)
    cols = regimes.columns

    def _joint(ind: pd.DataFrame) -> pd.DataFrame:
        m = pd.DataFrame(np.nan, index=cols, columns=cols, dtype=float)
        for a in cols:
            for b in cols:
                x, y = ind[a], ind[b]
                mask = x.notna() & y.notna()
                m.loc[a, b] = float((x[mask].astype(bool) & y[mask].astype(bool)).mean()) if mask.sum() else np.nan
        return m

    def _jaccard(ind: pd.DataFrame) -> pd.DataFrame:
        m = pd.DataFrame(np.nan, index=cols, columns=cols, dtype=float)
        for a in cols:
            for b in cols:
                x, y = ind[a].astype(bool), ind[b].astype(bool)
                mask = ind[a].notna() & ind[b].notna()
                xs, ys = x[mask], y[mask]
                union = int((xs | ys).sum())
                m.loc[a, b] = float((xs & ys).sum() / union) if union else np.nan
        return m

    return {
        "joint_high": _joint(high),
        "jaccard_high": _jaccard(high),
        "joint_extreme": _joint(ext),
    }


def feature_distance(features: pd.DataFrame) -> pd.DataFrame:
    """Euclidean distance on z-scored feature vectors (columns = features).

    Constant columns (zero variance across assets) are dropped before
    standardization to avoid division by zero.
    """
    x = features.astype(float)
    sd = x.std(ddof=1)
    keep = sd > 0
    z = (x.loc[:, keep] - x.loc[:, keep].mean()) / sd[keep]
    a = z.to_numpy()
    diff = a[:, None, :] - a[None, :, :]
    d = np.sqrt((diff**2).sum(axis=-1))
    return pd.DataFrame(d, index=features.index, columns=features.index)


def rolling_rv_corr(rv: pd.DataFrame, window: int = 250, min_periods: int = 120) -> dict[str, pd.DataFrame]:
    """Pairwise rolling log-RV correlation endpoints (start/end/mean)."""
    log_rv = np.log(rv.where(rv > 0))
    cols = list(rv.columns)
    out: dict[str, pd.DataFrame] = {
        stat: pd.DataFrame(np.nan, index=cols, columns=cols, dtype=float) for stat in ("start", "end", "mean")
    }
    for i, a in enumerate(cols):
        for b in cols[i:]:
            pairs = pd.DataFrame({"a": log_rv[a], "b": log_rv[b]}).dropna()
            if len(pairs) < min_periods:
                continue
            cov = pairs["a"].rolling(window, min_periods=min_periods).cov(pairs["b"])
            va = pairs["a"].rolling(window, min_periods=min_periods).var(ddof=1)
            vb = pairs["b"].rolling(window, min_periods=min_periods).var(ddof=1)
            rc = (cov / np.sqrt(va * vb)).replace([np.inf, -np.inf], np.nan).dropna()
            if rc.empty:
                continue
            out["start"].loc[a, b] = out["start"].loc[b, a] = float(rc.iloc[0])
            out["end"].loc[a, b] = out["end"].loc[b, a] = float(rc.iloc[-1])
            out["mean"].loc[a, b] = out["mean"].loc[b, a] = float(rc.mean())
    return out
