#!/usr/bin/env python3
"""Inspect current data ranges in walk-forward signal parquets."""
import pandas as pd
from pathlib import Path

WALKDIR = Path("scripts/walkforward")
for pq in sorted(WALKDIR.glob("*_wf_signals_retrained.parquet")):
    df = pd.read_parquet(pq)
    asset = pq.name.replace("_wf_signals_retrained.parquet", "")
    print(f"{asset:10s}  rows={len(df):5d}  {str(df.index.min().date()):12s} -> {str(df.index.max().date()):12s}  buy={int((df.signal==1).sum()):4d}  sell={int((df.signal==-1).sum()):4d}  flat={int((df.signal==0).sum()):4d}")
