#!/usr/bin/env python3
"""
Replay attribution — offline CounterfactualEngine-based layer attribution.

Reads trade data (lifecycle results JSON), enriches each trade with all six
layer attributions using the TradeAttributionCalculator, and optionally loads
DecisionProvenance records from SQLite for authoritative calibration replay.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/research/replay_attribution.py \\
        --trades data/processed/trade_lifecycle_results.json \\
        --output data/research/attribution_replayed.json

Use --provenance-db to enable provenance-based calibration replay:
    PYTHONPATH=$PYTHONPATH:. python scripts/research/replay_attribution.py \\
        --provenance-db data/live/provenance.db \\
        --asset GBPUSD --verbose
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.attribution.replay import main

if __name__ == "__main__":
    main()
