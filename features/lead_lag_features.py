"""Optional lead-lag features promoted from research/lead_lag results."""

from __future__ import annotations

import logging
import os

import pandas as pd

from features.pair_specific import build_lead_lag_features

logger = logging.getLogger("eigencapital.lead_lag_features")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EDGES_PATH = os.path.join(PROJECT_ROOT, "data", "research", "lead_lag_edges.yaml")

# Curated edges (target_ticker, leader_ticker, lag_days, column_name)
# Populated from research; extend after running run_lead_lag.py
DEFAULT_LEAD_LAG_EDGES: list[dict] = [
    {
        "target": "AUDJPY=X",
        "leader": "NZDJPY=X",
        "lag": 3,
        "column": "nzdjpy_lead_3",
    },
    {
        "target": "CADJPY=X",
        "leader": "^DJI",
        "lag": 1,
        "column": "dji_lead_1",
    },
    {
        "target": "USDCAD=X",
        "leader": "^DJI",
        "lag": 1,
        "column": "dji_lead_1",
    },
    {
        "target": "NZDJPY=X",
        "leader": "^DJI",
        "lag": 1,
        "column": "dji_lead_1",
    },
    {
        "target": "EURAUD=X",
        "leader": "^DJI",
        "lag": 1,
        "column": "dji_lead_1",
    },
    {
        "target": "AUDJPY=X",
        "leader": "^DJI",
        "lag": 1,
        "column": "dji_lead_1",
    },
    {
        "target": "GBPJPY=X",
        "leader": "^DJI",
        "lag": 1,
        "column": "dji_lead_1",
    },
    {
        "target": "USDJPY=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "USDCHF=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "EURCHF=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "GBPCHF=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "GBPJPY=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "NZDJPY=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "CADCHF=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "NZDCHF=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "AUDCHF=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "CHFJPY=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "EURJPY=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
    {
        "target": "CADJPY=X",
        "leader": "GC=F",
        "lag": 1,
        "column": "gc_lead_1",
    },
]


def load_lead_lag_edges(path: str | None = None) -> list[dict]:
    path = path or DEFAULT_EDGES_PATH
    if not os.path.exists(path):
        return list(DEFAULT_LEAD_LAG_EDGES)
    import yaml

    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("edges", DEFAULT_LEAD_LAG_EDGES)


def apply_lead_lag_features(
    target_df: pd.DataFrame,
    leader_df: pd.DataFrame,
    lag: int,
    column_name: str,
) -> pd.Series:
    return build_lead_lag_features(target_df, leader_df, lag=lag).rename(column_name)
