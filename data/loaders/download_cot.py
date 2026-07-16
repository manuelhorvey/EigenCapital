import pandas as pd
import requests
import zipfile
import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data.loaders.cot_loader import FX_COT_CONTRACTS

COT_URL = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

COT_COLUMNS = [
    "Market_and_Exchange_Names",
    "Open_Interest_All",
    "Dealer_Positions_Long_All",
    "Dealer_Positions_Short_All",
    "Dealer_Positions_Spread_All",
    "Asset_Mgr_Positions_Long_All",
    "Asset_Mgr_Positions_Short_All",
    "Asset_Mgr_Positions_Spread_All",
    "Lev_Money_Positions_Long_All",
    "Lev_Money_Positions_Short_All",
    "Lev_Money_Positions_Spread_All",
    "Other_Rept_Positions_Long_All",
    "Other_Rept_Positions_Short_All",
    "Other_Rept_Positions_Spread_All",
    "Tot_Rept_Positions_Long_All",
    "Tot_Rept_Positions_Short_All",
    "NonRept_Positions_Long_All",
    "NonRept_Positions_Short_All",
]


def download_year(year: int) -> pd.DataFrame | None:
    url = COT_URL.format(year=year)
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [{year}] Download failed: {e}")
        return None

    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        print(f"  [{year}] Not a valid zip file")
        return None

    csv_filename = [f for f in z.namelist() if f.endswith(".txt") or f.endswith(".csv")]
    if not csv_filename:
        print(f"  [{year}] No CSV/TXT found in zip")
        return None

    with z.open(csv_filename[0]) as f:
        df = pd.read_csv(f, low_memory=False)

    date_cols = [c for c in df.columns if "Report_Date_as_" in c]
    if not date_cols:
        print(f"  [{year}] No date column found")
        return None
    date_col = date_cols[0]

    df = df[COT_COLUMNS + [date_col]]

    df[date_col] = pd.to_datetime(df[date_col])
    df.rename(columns={date_col: "date"}, inplace=True)

    market_col = "Market_and_Exchange_Names"
    fx_keys = set(FX_COT_CONTRACTS.values())
    mask = df[market_col].apply(
        lambda x: any(k.lower() in str(x).lower() for k in fx_keys)
    )
    df = df[mask].copy()

    for col in df.select_dtypes(include="object").columns:
        if col not in ("Market_and_Exchange_Names", "Contract_Units"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df.sort_values(["Market_and_Exchange_Names", "date"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"  [{year}] {len(df)} FX rows ({df['Market_and_Exchange_Names'].nunique()} contracts)")
    return df


def download_all_years(
    start_year: int = 2006,
    end_year: int | None = None,
    path: str = "data/processed/trade_data/cot_raw.parquet",
) -> pd.DataFrame:
    if end_year is None:
        end_year = pd.Timestamp.now().year

    all_dfs = []
    for year in range(start_year, end_year + 1):
        df = download_year(year)
        if df is not None and len(df) > 0:
            all_dfs.append(df)

    if not all_dfs:
        print("No data downloaded.")
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined.sort_values(["Market_and_Exchange_Names", "date"], inplace=True)
    combined.drop_duplicates(subset=["Market_and_Exchange_Names", "date"], keep="last", inplace=True)
    combined.reset_index(drop=True, inplace=True)
    combined.to_parquet(path)
    print(f"\nSaved {len(combined)} rows x {len(combined.columns)} cols to {path}")
    return combined


if __name__ == "__main__":
    download_all_years()
