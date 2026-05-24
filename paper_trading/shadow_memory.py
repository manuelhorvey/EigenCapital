import json
import os
import threading
from collections import Counter
from datetime import datetime, timedelta

import numpy as np

_lock = threading.Lock()

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "shadow_memory")

BASELINE_DIR = os.path.join(MEMORY_DIR, "baseline")


def store_event(asset: str, event: dict) -> None:
    try:
        ts = event.get("timestamp", datetime.utcnow().isoformat())
        date_str = ts[:10] if isinstance(ts, str) else datetime.utcnow().strftime("%Y-%m-%d")
        path = os.path.join(MEMORY_DIR, asset, f"{date_str}.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock, open(path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass


def read_events(asset: str, days: int = 90) -> list:
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        events = []
        asset_dir = os.path.join(MEMORY_DIR, asset)
        if not os.path.isdir(asset_dir):
            return events
        for fname in sorted(os.listdir(asset_dir)):
            if not fname.endswith(".jsonl"):
                continue
            date_str = fname.replace(".jsonl", "")
            try:
                fdate = datetime.strptime(date_str, "%Y-%m-%d")
                if fdate < cutoff:
                    continue
            except ValueError:
                continue
            fpath = os.path.join(asset_dir, fname)
            try:
                with open(fpath) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            events.append(json.loads(line))
            except Exception:
                continue
        return events
    except Exception:
        return []


def _histogram_bins(values: list, bins: int = 10, low: float = 0.0, high: float = 1.0) -> list:
    if not values:
        return []
    hist, edges = np.histogram(values, bins=bins, range=(low, high))
    return [
        {"bin_start": float(edges[i]), "bin_end": float(edges[i + 1]), "count": int(hist[i])} for i in range(len(hist))
    ]


def _kl_divergence(p: list, q: list) -> float:
    p = np.array(p, dtype=np.float64)
    q = np.array(q, dtype=np.float64)
    p = p / (p.sum() + 1e-12)
    q = q / (q.sum() + 1e-12)
    q = np.clip(q, 1e-12, None)
    return float(np.sum(p * np.log(p / q)))


def build_baseline(asset: str, events: list | None = None) -> dict:
    if events is None:
        events = read_events(asset, days=90)

    baseline = {
        "asset": asset,
        "timestamp": datetime.utcnow().isoformat(),
        "event_count": len(events),
    }

    if not events:
        return baseline

    proba_short, proba_neutral, proba_long = [], [], []
    signal_match_count = 0
    signal_total = 0
    pnl_diffs = []
    regime_counts = Counter()
    sl_deltas, tp_deltas = [], []

    for e in events:
        md = e.get("model_divergence", {})
        cur = md.get("current", {})
        if cur.get("proba_short") is not None:
            proba_short.append(cur["proba_short"])
            proba_neutral.append(cur["proba_neutral"])
            proba_long.append(cur["proba_long"])

        sd = e.get("signal_divergence", {})
        if sd:
            signal_total += 1
            if sd.get("match"):
                signal_match_count += 1

        pnl = e.get("pnl_decomposition", {})
        if pnl.get("original_pnl") is not None and pnl.get("computed_pnl") is not None:
            pnl_diffs.append(abs(pnl["original_pnl"] - pnl["computed_pnl"]))

        rc = e.get("regime_context", {})
        if rc.get("volatility_regime"):
            regime_counts[rc["volatility_regime"]] += 1

        sltp = e.get("sltp_drift", {})
        if sltp.get("sl_delta_pct") is not None:
            sl_deltas.append(sltp["sl_delta_pct"])
        if sltp.get("tp_delta_pct") is not None:
            tp_deltas.append(sltp["tp_delta_pct"])

    baseline["model_proba_distribution"] = {
        "short": _histogram_bins(proba_short),
        "neutral": _histogram_bins(proba_neutral),
        "long": _histogram_bins(proba_long),
        "count": len(proba_short),
    }

    baseline["signal_distribution"] = {
        "total": signal_total,
        "matches": signal_match_count,
        "mismatch_rate": round(1.0 - (signal_match_count / signal_total), 4) if signal_total > 0 else 0.0,
    }

    baseline["regime_distribution"] = dict(regime_counts)

    if pnl_diffs:
        baseline["pnl_mismatch_stats"] = {
            "mean_abs_error": round(float(np.mean(pnl_diffs)), 10),
            "max_abs_error": round(float(np.max(pnl_diffs)), 10),
            "count": len(pnl_diffs),
        }

    if sl_deltas:
        baseline["sltp_drift_stats"] = {
            "mean_sl_delta_pct": round(float(np.mean(sl_deltas)), 4),
            "max_sl_delta_pct": round(float(np.max(sl_deltas)), 4),
            "mean_tp_delta_pct": round(float(np.mean(tp_deltas)), 4) if tp_deltas else 0.0,
            "max_tp_delta_pct": round(float(np.max(tp_deltas)), 4) if tp_deltas else 0.0,
            "sl_adjustment_count": len(sl_deltas),
            "tp_adjustment_count": len(tp_deltas),
        }

    return baseline


def save_baseline(asset: str, baseline: dict) -> None:
    try:
        os.makedirs(BASELINE_DIR, exist_ok=True)
        path = os.path.join(BASELINE_DIR, f"{asset}.json")
        with open(path, "w") as f:
            json.dump(baseline, f, indent=2, default=str)
    except Exception:
        pass


def load_baseline(asset: str) -> dict | None:
    try:
        path = os.path.join(BASELINE_DIR, f"{asset}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def ensure_baseline(asset: str) -> dict:
    baseline = load_baseline(asset)
    if baseline is None:
        events = read_events(asset, days=90)
        baseline = build_baseline(asset, events)
        save_baseline(asset, baseline)
    return baseline
