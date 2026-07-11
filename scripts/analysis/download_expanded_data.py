#!/usr/bin/env python3
"""Download 10+ years of OHLCV data for all assets and save locally, then re-run walk-forward backtest with expanded data."""

import logging
import os
import sys
import json
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download_expanded")

ASSETS = {
    "AUDJPY": "AUDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "CADCHF": "CADCHF=X",
    "CADJPY": "CADJPY=X",
    "CHFJPY": "CHFJPY=X",
    "EURAUD": "EURAUD=X",
    "EURCAD": "EURCAD=X",
    "EURCHF": "EURCHF=X",
    "EURNZD": "EURNZD=X",
    "GBPAUD": "GBPAUD=X",
    "GBPCAD": "GBPCAD=X",
    "GBPCHF": "GBPCHF=X",
    "GBPJPY": "GBPJPY=X",
    "GBPUSD": "GBPUSD=X",
    "GC": "GC=F",
    "NZDCAD": "NZDCAD=X",
    "NZDCHF": "NZDCHF=X",
    "NZDJPY": "NZDJPY=X",
    "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X",
    "USDCHF": "USDCHF=X",
    "USDJPY": "USDJPY=X",
    "BTCUSD": "BTC-USD",
    "^DJI": "^DJI",
}

DATA_DIR = Path("data/yfinance_10yr")
DATA_DIR.mkdir(parents=True, exist_ok=True)


def download_asset_data(asset: str, ticker: str) -> pd.DataFrame:
    """Download 10+ years of OHLCV data from yfinance."""
    import yfinance as yf
    
    cache_path = DATA_DIR / f"{asset}_ohlcv.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        logger.info(f"{asset}: loaded {len(df)} rows from cache ({df.index.min().date()} -> {df.index.max().date()})")
        return df
    
    logger.info(f"{asset} ({ticker}): downloading from yfinance (max period)...")
    df = yf.download(ticker, period="max", auto_adjust=False, progress=False)
    if df is None or df.empty:
        logger.warning(f"{asset}: no data returned, trying 10y")
        df = yf.download(ticker, period="10y", auto_adjust=False, progress=False)
    if df is None or df.empty:
        logger.warning(f"{asset}: no data at all")
        return pd.DataFrame()
    
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    df.index = df.index.normalize()
    
    # Deduplicate
    df = df[~df.index.duplicated(keep="last")]
    df.to_parquet(cache_path)
    logger.info(f"{asset}: saved {len(df)} rows ({df.index.min().date()} -> {df.index.max().date()})")
    return df


def download_macro_data():
    """Download macro data (DXY, VIX, SPX) with max history."""
    import yfinance as yf
    
    macro_tickers = {
        "DX-Y.NYB": "dxy",
        "^VIX": "vix", 
        "^GSPC": "spx",
        "CL=F": "wti",
        "^TNX": "tnx",
    }
    
    result = {}
    for ticker, name in macro_tickers.items():
        cache_path = DATA_DIR / f"macro_{name}.parquet"
        if cache_path.exists():
            s = pd.read_parquet(cache_path)["close"]
            logger.info(f"macro {name}: loaded {len(s)} rows from cache")
            result[name] = s
            continue
        
        logger.info(f"macro {name} ({ticker}): downloading...")
        df = yf.download(ticker, period="max", auto_adjust=True, progress=False)
        if df is None or df.empty:
            logger.warning(f"macro {name}: no data")
            result[name] = pd.Series(dtype=float)
            continue
        
        s = df["Close"].squeeze().copy()
        s.index = s.index.tz_localize("UTC") if s.index.tz is None else s.index.tz_convert("UTC")
        s.index = s.index.normalize()
        s = s[~s.index.duplicated(keep="last")]
        s.name = "close"
        s.to_frame().to_parquet(cache_path)
        result[name] = s
        logger.info(f"macro {name}: {len(s)} rows ({s.index.min().date()} -> {s.index.max().date()})")
    
    return result


def compute_expanded_labels(asset: str, ohlcv: pd.DataFrame, tp_mult: float, sl_mult: float):
    """Compute triple-barrier labels on expanded OHLCV."""
    from labels.triple_barrier import apply_triple_barrier
    
    if ohlcv.empty:
        return pd.Series(dtype=int)
    
    labeled = apply_triple_barrier(ohlcv, pt_sl=[tp_mult, sl_mult], vertical_barrier=20)
    return labeled["label"].fillna(0).astype(int)


def compute_feature_balance(asset: str, df: pd.DataFrame):
    """Compute label class balance over time, by year, by volatility regime."""
    from scipy.stats import binomtest
    
    labels_series = df["label"].astype(int)
    labels = labels_series.values
    
    bu = int((labels == 1).sum())        # UP/TP hit
    sd = int((labels == -1).sum())       # DOWN/SL hit  
    hold = int((labels == 0).sum())      # HOLD/expired
    total = len(labels)
    non_hold = bu + sd
    up_rate = bu / max(non_hold, 1)
    
    # Yearly balance
    df_year = df.copy()
    df_year["year"] = df.index.year
    yearly = df_year.groupby("year")["label"].agg(["count", "mean", "sum"])
    
    # Session balance (first/last half of year)
    df_year["h1"] = df.index.month <= 6
    session = df_year.groupby("h1")["label"].agg(["count", "mean", "sum"])
    
    # Volatility quintiles
    returns = df["close"].pct_change().dropna()
    vol = returns.rolling(21).std()
    valid = vol.dropna()
    if len(valid) >= 10:
        vol_q = pd.qcut(valid.rank(method="first"), 5, labels=["low", "med_low", "med", "med_high", "high"])
        vol_labels = labels_series.loc[valid.index]
        vol_balance = {}
        for q in ["low", "med_low", "med", "med_high", "high"]:
            mask = vol_q == q
            if mask.sum() > 0:
                vol_balance[q] = {
                    "n": int(mask.sum()),
                    "up_rate": float(vol_labels[mask].mean()),
                }
    else:
        vol_balance = {}
    
    return {
        "n_total": total,
        "n_buy_labels": bu,
        "n_sell_labels": sd,
        "n_hold_labels": hold,
        "up_rate": round(up_rate, 4),
        "yearly": {str(k): {"n": int(v["count"]), "up_rate": round(float(v["mean"]), 4)} for k, v in yearly.iterrows()},
        "session": {("H1" if k else "H2"): {"n": int(v["count"]), "up_rate": round(float(v["mean"]), 4)} for k, v in session.iterrows()},
        "vol_regime": vol_balance,
    }


def main():
    # 1. Download expanded OHLCV
    logger.info("=" * 60)
    logger.info("STEP 1: Downloading expanded data (10+ years)")
    logger.info("=" * 60)
    
    macro = download_macro_data()
    
    all_balance: dict[str, dict] = {}
    all_ohlcv: dict[str, pd.DataFrame] = {}
    
    for asset, ticker in ASSETS.items():
        ohlcv = download_asset_data(asset, ticker)
        if ohlcv.empty:
            logger.warning(f"{asset}: skipping — no data")
            continue
        all_ohlcv[asset] = ohlcv
    
    # 2. Load per-asset pt_sl from config
    logger.info("=" * 60)
    logger.info("STEP 2: Computing labels & class balance on expanded data")
    logger.info("=" * 60)
    
    from paper_trading.config_manager import get_config
    cfg = get_config()
    
    for asset, ohlcv in sorted(all_ohlcv.items()):
        acfg = cfg.assets.get(asset, {})
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        
        labels = compute_expanded_labels(asset, ohlcv, tp, sl)
        df = ohlcv.copy()
        df["label"] = labels.reindex(ohlcv.index).fillna(0).astype(int)
        
        balance = compute_feature_balance(asset, df)
        balance["tp"] = tp
        balance["sl"] = sl
        all_balance[asset] = balance
        
        bu = balance["n_buy_labels"]
        sd = balance["n_sell_labels"]
        nbl = balance['n_buy_labels']; nsl = balance['n_sell_labels']; nhl = balance['n_hold_labels']
        non_h = nbl + nsl
        ur = balance['up_rate']
        logger.info(f"{asset:10s}  n={balance['n_total']:5d}  BUY_labels={nbl:4d} ({nbl/max(non_h,1)*100:5.1f}%)  SELL_labels={nsl:4d} ({nsl/max(non_h,1)*100:5.1f}%)  HOLD={nhl:4d} ({nhl/max(balance['n_total'],1)*100:5.1f}%)  UP_rate={ur:.3f}  tp={tp:.2f} sl={sl:.2f}")
    
    # 3. Print class balance analysis
    logger.info("=" * 60)
    logger.info("LABEL CLASS BALANCE SUMMARY (Expanded Data)")
    logger.info("=" * 60)
    
    header = f"{'Asset':>10s}  {'n_total':>7s}  {'BUY_lb':>7s}  {'SELL_lb':>8s}  {'HOLD%':>7s}  {'UP_rate':>7s}  {'tp':>5s}  {'sl':>5s}  {'n_years':>7s}"
    print(f"\n{header}")
    print("-" * 80)
    
    for asset in sorted(all_balance.keys()):
        b = all_balance[asset]
        n_years = b["n_total"] / 252
        non_h = b["n_buy_labels"] + b["n_sell_labels"]
        print(f"{asset:>10s}  {b['n_total']:>7d}  {b['n_buy_labels']:>4d} ({b['n_buy_labels']/max(non_h,1)*100:>4.1f}%)  {b['n_sell_labels']:>4d} ({b['n_sell_labels']/max(non_h,1)*100:>4.1f}%)  {b['n_hold_labels']/max(b['n_total'],1)*100:>6.1f}%  {b['up_rate']*100:>6.1f}%  {b['tp']:>4.1f}  {b['sl']:>4.1f}  {n_years:>6.1f}y")
    
    # 4. Save balance results
    balance_path = DATA_DIR / "label_balance_expanded.json"
    with open(balance_path, "w") as f:
        json.dump(all_balance, f, indent=2, default=str)
    logger.info(f"Label balance saved to {balance_path}")
    
    # 5. List assets with significant BUY/SELL label imbalance
    print("\n--- LABEL IMBALANCE ANALYSIS (non-HOLD only) ---")
    for asset in sorted(all_balance.keys()):
        b = all_balance[asset]
        up_rate = b["up_rate"]
        non_h = b["n_buy_labels"] + b["n_sell_labels"]
        if non_h == 0:
            continue
        from scipy.stats import binomtest
        p_val = binomtest(b["n_buy_labels"], non_h, p=0.5).pvalue
        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
        direction = "BUY-biased" if up_rate > 0.5 else "SELL-biased"
        print(f"{asset:>10s}  UP_rate={up_rate*100:>5.1f}%  BUY={b['n_buy_labels']:>4d}  SELL={b['n_sell_labels']:>4d}  HOLD={b['n_hold_labels']:>5d}  p={p_val:.4f} {sig}  {direction}")
    
    print("\nDone. Ready for expanded walk-forward backtest.")


if __name__ == "__main__":
    main()
