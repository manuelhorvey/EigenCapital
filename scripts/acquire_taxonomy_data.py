"""Taxonomy dataset acquisition — DATA_REQUIREMENTS steps 1-2 (engineering).

Pulls the 22 baseline-universe D1 symbols that are absent from the frozen
R5 snapshot, plus the Copper candidate (yfinance HG=F), into SEPARATE
directories so that data/mt5/R5_data_manifest.json verification
(r5_executor.verify_snapshot) remains byte-identical.

This script opens no trial slot, commits to no hypothesis, and must never
write into data/mt5/ (verify_snapshot hashes every *_D1.csv there).

Outputs:
    data/taxonomy_d1/<SYMBOL>_D1.csv            (Exness MT5 D1, 2020-01-01..2026-08-24)
    data/taxonomy_d1/taxonomy_data_manifest.json (R5-pattern frozen manifest)
    data/candidates/copper_hg_D1.csv             (yfinance HG=F candidate)
    data/candidates/candidates_manifest.json

Usage:
    python scripts/acquire_taxonomy_data.py            # acquire + freeze
    python scripts/acquire_taxonomy_data.py --verify   # re-verify manifests only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
TAXONOMY_DIR = REPO / "data" / "taxonomy_d1"
CANDIDATE_DIR = REPO / "data" / "candidates"
R5_MANIFEST = REPO / "data" / "mt5" / "R5_data_manifest.json"

# Baseline universe symbols absent from the frozen R5 snapshot.
NEW_BASELINE_SYMBOLS = [
    "AUDJPY",
    "AUDCHF",
    "AUDCAD",
    "NZDJPY",
    "GBPJPY",
    "AUDNZD",
    "NZDCHF",
    "NZDCAD",
    "GBPCHF",
    "GBPCAD",
    "CHFJPY",
    "EURJPY",
    "CADJPY",
    "XNGUSD",
    "EURCHF",
    "EURCAD",
    "CADCHF",
    "GBPNZD",
    "EURGBP",
    "EURNZD",
    "GBPAUD",
    "EURAUD",
]

# Align with the frozen R5 snapshot window (documented, explicit range).
DATE_FROM = datetime(2020, 1, 1, tzinfo=UTC)
DATE_TO = datetime(2026, 8, 24, 23, 59, tzinfo=UTC)
DATE_TO_EXCLUSIVE = pd.Timestamp("2026-08-25")

CSV_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def _combined_hash(paths: list[Path]) -> str:
    """R5-pattern combined hash: sha256 over sorted per-file sha256 hex digests."""
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: x.name):
        h.update(_sha256_file(p).encode())
    return h.hexdigest()


def _file_stats(path: Path) -> dict:
    df = pd.read_csv(path)
    tcol = df.columns[0]
    return {
        "sha256_prefix": _sha256_file(path)[:12],
        "sha256": _sha256_file(path),
        "rows": int(len(df)),
        "first": str(pd.to_datetime(df[tcol]).min().date()),
        "last": str(pd.to_datetime(df[tcol]).max().date()),
    }


def pull_mt5_symbols(symbols: list[str]) -> list[Path]:
    from mt5linux import MetaTrader5

    TAXONOMY_DIR.mkdir(parents=True, exist_ok=True)
    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        raise RuntimeError("MT5 bridge initialize() failed — start scripts/start_trading.sh --bridge-only")

    written: list[Path] = []
    try:
        acc = mt5.account_info()
        print(f"account={acc.login} server={acc.server} company={acc.company}")
        for sym in symbols:
            rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_D1, DATE_FROM, DATE_TO)
            if rates is None or len(rates) == 0:
                raise RuntimeError(f"no D1 rates returned for {sym}")
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df = df[df["time"] < DATE_TO_EXCLUSIVE]
            if df["time"].duplicated().any():
                raise RuntimeError(f"duplicate timestamps in {sym}")
            out = df.rename(columns={})[
                ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
            ].copy()
            # OHLC contract invariants (DATA_CONTRACT): fail loudly, never repair.
            bad = (
                (out["high"] < out[["open", "close"]].max(axis=1))
                | (out["low"] > out[["open", "close"]].min(axis=1))
                | (out[["open", "high", "low", "close"]] <= 0).any(axis=1)
            )
            if bad.any():
                raise RuntimeError(f"OHLC invariant violated for {sym}: {int(bad.sum())} rows")
            out["time"] = out["time"].dt.strftime("%Y-%m-%d")
            out = out[CSV_COLUMNS]
            path = TAXONOMY_DIR / f"{sym}_D1.csv"
            out.to_csv(path, index=False)
            written.append(path)
            print(f"  {sym}: {len(out)} rows {out['time'].iloc[0]} -> {out['time'].iloc[-1]}")
    finally:
        mt5.shutdown()
    return written


def pull_copper_candidate() -> Path:
    import yfinance as yf

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    df = yf.download(
        "HG=F",
        start=str(DATE_FROM.date()),
        end=str(DATE_TO.date()),
        interval="1d",
        progress=False,
        auto_adjust=False,
    )
    if df is None or len(df) == 0:
        raise RuntimeError("yfinance returned no rows for HG=F")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df = df.rename(columns={"Date": "time", "Volume": "tick_volume"})
    df["time"] = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%d")
    out = pd.DataFrame(
        {
            "time": df["time"],
            "open": df["Open"],
            "high": df["High"],
            "low": df["Low"],
            "close": df["Close"],
            "tick_volume": df.get("tick_volume", 0).fillna(0).astype(int),
            "spread": 0,
            "real_volume": 0,
        }
    )
    out = out[CSV_COLUMNS]
    path = CANDIDATE_DIR / "copper_hg_D1.csv"
    out.to_csv(path, index=False)
    print(f"  COPPER(HG=F): {len(out)} rows {out['time'].iloc[0]} -> {out['time'].iloc[-1]}")
    return path


def freeze_manifests(new_paths: list[Path], copper_path: Path | None) -> dict:
    """Write R5-pattern manifests. Never touches data/mt5/R5_data_manifest.json."""
    # Baseline files borrowed read-only from the frozen R5 snapshot (12 assets + USOIL candidate).
    borrowed = sorted(
        p
        for p in (REPO / "data" / "mt5").glob("*_D1.csv")
        if p.name.replace("_D1.csv", "").removesuffix("m")
        in {
            "US30",
            "USTEC",
            "AUDUSD",
            "NZDUSD",
            "GBPUSD",
            "USDJPY",
            "XAUUSD",
            "XAGUSD",
            "EURUSD",
            "USDCHF",
            "USDCAD",
            "BTCUSD",
            "USOIL",
        }
    )
    with open(R5_MANIFEST) as fh:
        r5 = json.load(fh)

    tax_files = sorted(new_paths, key=lambda p: p.name)
    tax_manifest = {
        "snapshot_id": "VOL_TAXONOMY_D1_SUPPLEMENT_V1",
        "created": datetime.now(UTC).strftime("%Y-%m-%d"),
        "source": "exness_mt5_D1_via_rpyc_bridge_127.0.0.1:8001 (account 436921728, Exness-MT5Trial9)",
        "n_instruments": len(tax_files),
        "date_range_policy": "explicit pull window 2020-01-01..2026-08-24 (aligned to R5 frozen snapshot end)",
        "per_file": {p.name: _file_stats(p) for p in tax_files},
        "combined_sha256": _combined_hash(tax_files),
        "borrowed_from_r5_snapshot": {
            "manifest": "data/mt5/R5_data_manifest.json",
            "r5_combined_sha256": r5["combined_sha256"],
            "files": {p.name: _file_stats(p) for p in borrowed},
        },
        "note": (
            "Engineering manifest (DATA_REQUIREMENTS steps 1-2). Opens no trial slot. "
            "Supplement files live outside data/mt5/ so R5 verify_snapshot stays byte-identical. "
            "Borrowed files are read-only references into the frozen R5 snapshot."
        ),
    }
    tax_path = TAXONOMY_DIR / "taxonomy_data_manifest.json"
    with open(tax_path, "w") as fh:
        json.dump(tax_manifest, fh, indent=2)

    cand_manifest = None
    if copper_path is not None:
        cand_manifest = {
            "snapshot_id": "CANDIDATES_EXTERNAL_V1",
            "created": datetime.now(UTC).strftime("%Y-%m-%d"),
            "source": "yfinance HG=F (COMEX copper front future) — NOT an Exness symbol; provider documented explicitly per DATA_CONTRACT provider-precedence rule; candidate-only, never merged into baseline universe",
            "per_file": {copper_path.name: _file_stats(copper_path)},
            "combined_sha256": _combined_hash([copper_path]),
            "note": "Engineering manifest (DATA_REQUIREMENTS steps 1-2). Candidate asset evaluation only.",
        }
        cand_path = CANDIDATE_DIR / "candidates_manifest.json"
        with open(cand_path, "w") as fh:
            json.dump(cand_manifest, fh, indent=2)

    return {"taxonomy": tax_manifest, "candidates": cand_manifest}


def verify_all() -> bool:
    ok = True
    for mpath in (TAXONOMY_DIR / "taxonomy_data_manifest.json", CANDIDATE_DIR / "candidates_manifest.json"):
        if not mpath.exists():
            print(f"MISSING manifest: {mpath}")
            ok = False
            continue
        with open(mpath) as fh:
            m = json.load(fh)
        base = mpath.parent
        paths = [base / name for name in m["per_file"]]
        recomputed = _combined_hash(paths)
        match = recomputed == m["combined_sha256"]
        print(f"{mpath.name}: {'OK' if match else 'MISMATCH'} ({m['combined_sha256'][:16]}...)")
        ok = ok and match
    # R5 frozen snapshot must remain untouched.
    sys.path.insert(0, str(REPO / "src"))
    from eigencapital.research.campaigns.r5_executor import verify_snapshot

    r5_ok = verify_snapshot()
    print(f"R5 verify_snapshot: {'OK' if r5_ok else 'MISMATCH'}")
    return ok and r5_ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="re-verify manifests only")
    args = ap.parse_args()

    if args.verify:
        return 0 if verify_all() else 1

    print("Pulling 22 baseline D1 symbols via MT5 bridge...")
    paths = pull_mt5_symbols(NEW_BASELINE_SYMBOLS)
    print("Pulling Copper candidate (yfinance HG=F)...")
    copper = pull_copper_candidate()
    freeze_manifests(paths, copper)
    print("Freezing manifests...")
    if not verify_all():
        print("VERIFICATION FAILED")
        return 1
    print("Done. Manifests frozen; R5 snapshot intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
