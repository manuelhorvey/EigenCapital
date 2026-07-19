import json
import logging
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parent.parent)

logger = logging.getLogger("eigencapital.weekly_report")

BASE = Path(__file__).resolve().parent.parent
STATE_PATH = Path(BASE) / "data" / "live" / "state.json"
HISTORY_PATH = Path(BASE) / "data" / "live" / "history.parquet"
LOG_PATH = Path(BASE) / "data" / "live" / "weekly_log.csv"
TRADE_LOG_PATH = Path(BASE) / "data" / "live" / "paper_trade_log.md"

# Backtest baselines for signal distribution comparison
BACKTEST_BASELINES = {
    "XLF": {"buy_pct": 35, "sell_pct": 35, "flat_pct": 30, "mean_conf": 0.60},
    "BTC": {"buy_pct": 40, "sell_pct": 30, "flat_pct": 30, "mean_conf": 0.55},
    "NZDJPY": {"buy_pct": 45, "sell_pct": 25, "flat_pct": 30, "mean_conf": 0.55},
}

# Vol regime baselines (training period 2015-2022, EWM span=100)
TRAIN_VOLS = {
    "XLF": 0.0134,
    "BTC": 0.0377,
    "NZDJPY": 0.0070,
}

TICKERS = {
    "XLF": "XLF",
    "BTC": "BTC-USD",
    "NZDJPY": "NZDJPY=X",
}

VOL_RATIO_THRESHOLDS = {
    "healthy": (0.80, 1.20),
    "warning": (0.70, 1.30),
    "critical": (0.50, 1.50),
}


def compute_live_ewm_vol(ticker, span=100):
    df = yf.download(ticker, period="3mo", auto_adjust=True, progress=False)
    if df.empty:
        return None
    close = df["Close"] if "Close" in df.columns else df["close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    log_ret = np.log(close).diff()
    vol = log_ret.ewm(span=span).std()
    vals = vol.dropna()
    return float(vals.iloc[-1]) if not vals.empty else None


def check_vol_regime():
    logger.info("\n--- Vol Regime Check ---")
    all_healthy = True
    for name, ticker in TICKERS.items():
        train_vol = TRAIN_VOLS.get(name)
        live_vol = compute_live_ewm_vol(ticker)
        if live_vol is None or train_vol is None:
            logger.info("  %8s: unable to compute vol", name)
            continue
        ratio = live_vol / train_vol

        if ratio < VOL_RATIO_THRESHOLDS["critical"][0] or ratio > VOL_RATIO_THRESHOLDS["critical"][1]:
            status = "CRITICAL"
            all_healthy = False
        elif ratio < VOL_RATIO_THRESHOLDS["warning"][0] or ratio > VOL_RATIO_THRESHOLDS["warning"][1]:
            status = "WARNING"
            all_healthy = False
        elif ratio < VOL_RATIO_THRESHOLDS["healthy"][0] or ratio > VOL_RATIO_THRESHOLDS["healthy"][1]:
            status = "WARNING"
        else:
            status = "healthy"

        logger.info(
            "  %8s: train_vol=%.4f  live_vol=%.4f  ratio=%.2f  → %s%s",
            name,
            train_vol,
            live_vol,
            ratio,
            status,
            " ⚠" if status != "healthy" else "",
        )
    return all_healthy


def log_vol_baseline():
    entries = []
    for name, ticker in TICKERS.items():
        train_vol = TRAIN_VOLS.get(name)
        live_vol = compute_live_ewm_vol(ticker)
        if live_vol is None:
            continue
        ratio = live_vol / train_vol
        entries.append((name, train_vol, live_vol, ratio))
    today = datetime.now().strftime("%Y-%m-%d")

    md = (
        f"# Paper Trade Log\n\n"
        f"## {today} — Vol Regime Baseline\n\n"
        f"Initial vol regime readings at paper trade start. "
        f"Training period: 2015-2022, EWM span=100.\n\n"
        f"| Asset | Train Vol | Live Vol | Ratio | Status |\n"
        f"|-------|-----------|----------|-------|--------|\n"
    )
    for name, tv, lv, ratio in entries:
        if ratio < VOL_RATIO_THRESHOLDS["critical"][0] or ratio > VOL_RATIO_THRESHOLDS["critical"][1]:
            status = "CRITICAL"
        elif ratio < VOL_RATIO_THRESHOLDS["warning"][0] or ratio > VOL_RATIO_THRESHOLDS["warning"][1]:
            status = "WARNING"
        else:
            status = "healthy"
        md += f"| {name:6s} | {tv:.4f} | {lv:.4f} | {ratio:.2f} | {status} |\n"

    md += (
        "\nLive vol is structurally lower than 2015-2022 training period. "
        "Walk-forward already captured some of this — 2022-2024 windows\n"
        "showed lower vol than early training years. Effect on performance "
        "to be measured over 6-month paper trade period.\n"
        "Action: retrain with vol-adjusted barriers in January 2027.\n"
    )

    # Append to log
    if Path(TRADE_LOG_PATH).exists():
        with open(TRADE_LOG_PATH) as f:
            existing = f.read()
        if today not in existing:
            with open(TRADE_LOG_PATH, "a") as f:
                f.write("\n\n" + md)
    else:
        Path(Path(TRADE_LOG_PATH).parent).mkdir(parents=True, exist_ok=True)
        with open(TRADE_LOG_PATH, "w") as f:
            f.write(md)
    logger.info("\nVol baseline logged to %s", TRADE_LOG_PATH)


def run():
    state = load_state()
    if state is None:
        logger.warning("No state found.")
        return
    hist = load_history()

    logger.info("\n%s", "=" * 70)
    logger.info("WEEKLY PORTFOLIO REPORT — %s", datetime.now().strftime("%Y-%m-%d"))
    logger.info("%s", "=" * 70)

    portfolio = state.get("portfolio", {})
    tv = portfolio.get("total_value", 0)
    tr = portfolio.get("total_return", 0)
    days = portfolio.get("days_running", 0)
    logger.info("\nPortfolio: $%.2f  Return: %+.2f%%  Days: %d", tv, tr, days)

    # Signal distribution check
    logger.info("\n--- Signal Distribution Check ---")
    for name in ["XLF", "BTC", "NZDJPY"]:
        asset = state.get("assets", {}).get(name, {})
        metrics = asset.get("metrics", {})
        sig_dist = metrics.get("signal_distribution", {})
        buy = sig_dist.get("BUY", 0)
        sell = sig_dist.get("SELL", 0)
        flat = sig_dist.get("FLAT", 0)
        total = buy + sell + flat
        buy_pct = buy / total * 100 if total > 0 else 0
        sell_pct = sell / total * 100 if total > 0 else 0
        baseline = BACKTEST_BASELINES.get(name, {})
        b_buy = baseline.get("buy_pct", 33)
        b_sell = baseline.get("sell_pct", 33)

        buy_drift = abs(buy_pct - b_buy)
        sell_drift = abs(sell_pct - b_sell)
        stable = buy_drift < 15 and sell_drift < 15

        logger.info(
            "  %8s: Live B/S %.0f/%.0f vs BT %d/%d → %s (buy_d=%.0fpp sell_d=%.0fpp)",
            name,
            buy_pct,
            sell_pct,
            b_buy,
            b_sell,
            "STABLE" if stable else "DRIFT",
            buy_drift,
            sell_drift,
        )

    # Confidence drift check
    logger.info("\n--- Confidence Trend Check ---")
    for name in ["XLF", "BTC", "NZDJPY"]:
        asset = state.get("assets", {}).get(name, {})
        metrics = asset.get("metrics", {})
        mean_conf = metrics.get("mean_confidence", 0) / 100
        baseline_conf = BACKTEST_BASELINES.get(name, {}).get("mean_conf", 0.55)
        drift = abs(mean_conf - baseline_conf)
        logger.info(
            "  %8s: Live conf=%.2f vs BT=%.2f → %s (d=%.3f)",
            name,
            mean_conf,
            baseline_conf,
            "STABLE" if drift < 0.15 else "DRIFT",
            drift,
        )

    # Drawdown warning
    logger.info("\n--- Drawdown Status ---")
    for name in ["XLF", "BTC", "NZDJPY"]:
        asset = state.get("assets", {}).get(name, {})
        metrics = asset.get("metrics", {})
        dd = metrics.get("drawdown", 0) / 100
        limits = {"XLF": -0.08, "BTC": -0.15, "NZDJPY": -0.06}
        limit = limits.get(name, -0.10)
        pct_to_halt = (dd - limit) / abs(limit) * 100 if limit < 0 else 0
        logger.info("  %8s: DD=%.2f%% limit=%.0f%% → %.0f%% of halt distance", name, dd * 100, limit * 100, pct_to_halt)

    # Vol regime check
    check_vol_regime()
    log_vol_baseline()

    # Weekly PnL
    if len(hist) > 5:
        logger.info("\n--- Weekly PnL ---")
        recent = hist.tail(7)
        for _, r in recent.iterrows():
            date = r.get("date", "")
            pnl_pct = 0
            for name in ["XLF", "BTC", "NZDJPY"]:
                pnl_pct += r.get(f"{name}_return", 0) / 3
            logger.info("  %s: avg return %+.2f%%", date, pnl_pct)

    # Log to CSV
    log_entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "portfolio_value": tv,
        "portfolio_return": tr,
        "days_running": days,
    }
    for name in ["XLF", "BTC", "NZDJPY"]:
        asset = state.get("assets", {}).get(name, {})
        metrics = asset.get("metrics", {})
        log_entry[f"{name}_return"] = metrics.get("total_return", 0)
        log_entry[f"{name}_dd"] = metrics.get("drawdown", 0)
        log_entry[f"{name}_pf"] = metrics.get("profit_factor", 0)
        sig_dist = metrics.get("signal_distribution", {})
        log_entry[f"{name}_buy_pct"] = sig_dist.get("BUY", 0)
        log_entry[f"{name}_sell_pct"] = sig_dist.get("SELL", 0)
        live_vol = compute_live_ewm_vol(TICKERS[name])
        if live_vol is not None:
            log_entry[f"{name}_vol_ratio"] = round(live_vol / TRAIN_VOLS[name], 2)
    log_df = pd.DataFrame([log_entry])
    if Path(LOG_PATH).exists():
        existing = pd.read_csv(LOG_PATH)
        log_df = pd.concat([existing, log_df], ignore_index=True)
    log_df.to_csv(LOG_PATH, index=False)
    logger.info("\nWeekly log saved to %s", LOG_PATH)


def load_state():
    if Path(STATE_PATH).exists():
        with open(STATE_PATH) as f:
            return json.load(f)
    return None


def load_history():
    if Path(HISTORY_PATH).exists():
        return pd.read_parquet(HISTORY_PATH)
    return pd.DataFrame()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()
