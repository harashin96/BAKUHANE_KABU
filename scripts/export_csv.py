"""保存済みの株価データ(parquet)を圧縮CSV(data/prices.csv.gz)に書き出す

    python scripts/export_csv.py
"""
import _bootstrap  # noqa: F401

import pandas as pd

from jpstocks.data import PRICES, PRICES_CSV

df = pd.read_parquet(PRICES)
df.to_csv(PRICES_CSV, index=False, compression="gzip")
print(f"書き出し: {PRICES_CSV}  {len(df):,} 行")
