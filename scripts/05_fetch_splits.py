"""STEP 5: 株式分割・併合の履歴を取得(財務データの株数を株価と同じ基準にそろえるため)

    python scripts/05_fetch_splits.py

5〜10分ほど。研究・運用の前に、月1回くらい実行し直す
"""
import _bootstrap  # noqa: F401

from jpstocks.config import setup_logging
from jpstocks.data import fetch_splits, load_universe

setup_logging("fetch")
uni = load_universe()
df = fetch_splits(uni["ticker"].tolist())
print(df.sort_values("date").tail(15).to_string(index=False))
print(f"\n直近1年の分割・併合: {(df['date'] >= df['date'].max() - __import__('pandas').Timedelta(days=365)).sum()} 件")
