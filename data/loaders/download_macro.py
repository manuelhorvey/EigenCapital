import pandas as pd
import pandas_datareader.data as web
from datetime import datetime
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from data.loaders.macro_loader import FRED_SERIES


def download_all(start='1990-01-01', end='2026-12-31',
                 path='data/processed/trade_data/macro_factors.parquet'):
    raw_series = {}
    for name, series_id in FRED_SERIES.items():
        if series_id is None:
            continue
        try:
            data = web.DataReader(series_id, 'fred', start, end)
            raw_series[name] = data.iloc[:, 0]
            print(f'  {name:20s} ({series_id:20s}): {len(data)} rows')
        except Exception as e:
            print(f'  {name:20s} ({series_id:20s}): FAILED - {str(e)[:60]}')

    df = pd.DataFrame(raw_series)
    df.index.name = 'DATE'
    df.to_parquet(path)
    print(f'\nSaved {len(df)} rows x {len(df.columns)} cols to {path}')


if __name__ == '__main__':
    download_all()
