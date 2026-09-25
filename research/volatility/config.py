"""Frozen configuration for the volatility-taxonomy research artifact.

Every constant that could influence a reported number lives here so the
reproducibility record can pin them. Changing a constant creates a new
config version — never silently reuse results across config changes.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CONFIG_VERSION = "vol_taxonomy_v1"

# ── Frozen baseline universe (brief §2; not the code ASSET_CLASSES) ──
ASSET_CLASSES: dict[str, str] = {
    "US30": "indices",
    "USTEC": "indices",
    "AUDJPY": "forex",
    "AUDUSD": "forex",
    "AUDCHF": "forex",
    "AUDCAD": "forex",
    "NZDJPY": "forex",
    "GBPJPY": "forex",
    "AUDNZD": "forex",
    "NZDUSD": "forex",
    "NZDCHF": "forex",
    "NZDCAD": "forex",
    "GBPUSD": "forex",
    "GBPCHF": "forex",
    "GBPCAD": "forex",
    "CHFJPY": "forex",
    "EURJPY": "forex",
    "USDJPY": "forex",
    "CADJPY": "forex",
    "XAUUSD": "metals",
    "XAGUSD": "metals",
    "XNGUSD": "energy",
    "EURUSD": "forex",
    "EURCHF": "forex",
    "USDCHF": "forex",
    "EURCAD": "forex",
    "USDCAD": "forex",
    "CADCHF": "forex",
    "GBPNZD": "forex",
    "EURGBP": "forex",
    "EURNZD": "forex",
    "GBPAUD": "forex",
    "EURAUD": "forex",
    "BTCUSD": "crypto",
}

BASELINE_ASSETS: list[str] = sorted(ASSET_CLASSES)

# External candidates — never part of the baseline, never production.
CANDIDATE_ASSETS: dict[str, str] = {
    "USOIL": "energy",  # Exness WTI CFD, frozen inside data/mt5 R5 snapshot
    "COPPER": "metals",  # yfinance HG=F front future (documented provider)
}

# Asset → CSV stem. The 13 R5-frozen assets use Exness 'm'-suffixed stems;
# the 21 supplement assets use plain stems (broker symbol names differ).
# USOIL uses its frozen 'm' stem as an external candidate reference.
CSV_STEMS: dict[str, str] = {
    **{
        a: f"{a}m"
        for a in (
            "US30",
            "USTEC",
            "AUDUSD",
            "EURUSD",
            "NZDUSD",
            "GBPUSD",
            "USDJPY",
            "USDCAD",
            "USDCHF",
            "XAUUSD",
            "XAGUSD",
            "BTCUSD",
            "USOIL",
        )
    },
    **{
        a: a
        for a in (
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
        )
    },
    "COPPER": "copper_hg",
}

FROZEN_DIR = REPO / "data" / "mt5"
FROZEN_MANIFEST = FROZEN_DIR / "R5_data_manifest.json"
SUPPLEMENT_DIR = REPO / "data" / "taxonomy_d1"
SUPPLEMENT_MANIFEST = SUPPLEMENT_DIR / "taxonomy_data_manifest.json"
CANDIDATE_DIR = REPO / "data" / "candidates"
CANDIDATE_MANIFEST = CANDIDATE_DIR / "candidates_manifest.json"

# ── Sample windows (documented, pre-specified) ──────────────────────
# Primary: common window covering every baseline asset incl. XNGUSD
# (history starts 2022-03-20) plus a 60-bar RV warmup.
PRIMARY_START = "2022-06-01"
PRIMARY_END = "2026-08-24"
# Robustness: full sample on the 33 assets with 2020 history (XNG excluded).
FULL_START = "2020-06-01"
FULL_END = "2026-08-24"
XNGUSD = "XNGUSD"

# ── Volatility measurement ──────────────────────────────────────────
RV_WINDOWS = (5, 10, 20, 60)
PRIMARY_RV = 20
ANNUALIZATION = 252  # canonical: features/base/volatility.py daily_vol * sqrt(252)

# ── Regimes (PIT rolling) ───────────────────────────────────────────
REGIME_METHODS = ("percentile", "zscore")
REGIME_WINDOW = 500  # rolling bars for percentile / z-score
REGIME_MIN_PERIODS = 250
REGIME_CUTS_PCTILE = (0.25, 0.75, 0.95)  # LOW <P25, NORMAL 25-75, HIGH 75-95, EXTREME >P95
# z-score cutpoints = standard-normal quantiles matching the percentile cuts
REGIME_CUTS_Z = (-0.6744897501960817, 0.6744897501960817, 1.6448536269514722)
REGIME_LABELS = ("LOW", "NORMAL", "HIGH", "EXTREME")

# ── Clustering ──────────────────────────────────────────────────────
CLUSTER_K_CANDIDATES = (2, 3, 4, 5, 6)
LINKAGE_METHODS = ("average", "ward")
DISTANCE_METHODS = ("euclidean", "correlation")
PRIMARY_LINKAGE = "average"
PRIMARY_DISTANCE = "euclidean"
PCA_VAR_THRESHOLD = 0.90
RANDOM_SEED = 42  # any stochastic sensitivity step (kmeans check only)

# ── Temporal stability ──────────────────────────────────────────────
N_CHRONO_SUBSAMPLES = 3  # early / middle / recent thirds
ROLLING_STABILITY_WINDOW = 750  # bars
ROLLING_STABILITY_STEP = 250

# ── Candidate / LOO ─────────────────────────────────────────────────
NEAREST_NEIGHBORS = 3

# ── Trade-path (Question B) ─────────────────────────────────────────
TRADE_SYMBOLS = [
    "AUDUSDm",
    "NZDUSDm",
    "GBPUSDm",
    "EURUSDm",
    "USDCHFm",
    "USDCADm",
    "USDJPYm",
    "XAUUSDm",
]
# Frozen R4 replica parameters (export_r4_trade_stream defaults; config overrides)
R4_LOOKBACK = 252
R4_SKIP = 21
R4_RISK_LOOKBACK = 20
R4_VOL_LOOKBACK = 60
R4_VOL_SCALE_REFERENCE = 0.50
R4_WEIGHT_CLIP = 0.20
R4_REBALANCE_EVERY = 5
R4_COST_ONE_WAY = 15.0 / 10_000  # 10 bps transaction + 5 bps slippage

# Pre-specified (NOT optimized) trade-path thresholds:
LARGE_MOVE_K_SIGMA = 3.0  # MFE_ret > 3 * daily sigma at entry
INITIAL_PHASE_BARS = 3  # "initial underwater/flat phase" length
SIGMA_HALF_SIGMA = 0.5  # type-B adverse threshold (sigma units)
MIN_CELL_TRADES = 20  # regime-conditional cells below this are INSUFFICIENT DATA

# Declared multiple-testing families (counted, corrected when inferential):
H_FAMILIES = {
    "H1_H4_pooled_spearman": 4,  # underwater, oscillation, ttf, tmfe vs entry RV pctile
    "H_within_asset_spearman": 4 * 8,  # 4 metrics x 8 trade symbols
    "F_regime_definition_checks": 4,  # F10 across regime/horizon variants
}
