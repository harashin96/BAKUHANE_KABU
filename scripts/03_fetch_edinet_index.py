"""STEP 3: EDINETの書類一覧を日付ごとに取得(有価証券報告書・半期・四半期報告書だけ残す)

    python scripts/03_fetch_edinet_index.py            # 過去10年分(EDINETが公開している期間)
    python scripts/03_fetch_edinet_index.py --start 2024-01-01

途中で止めても、もう一度実行すれば続きから。1日1回の通信で、10年分で約2,600回・30〜60分程度。
"""
import argparse
from datetime import date, timedelta

import _bootstrap  # noqa: F401

from jpstocks.config import setup_logging
from jpstocks.edinet import INDEX, api_key, build_index, load_index

setup_logging("edinet")
ap = argparse.ArgumentParser()
ap.add_argument("--start", default=None)
ap.add_argument("--end", default=None)
a = ap.parse_args()
end = date.fromisoformat(a.end) if a.end else date.today()
start = date.fromisoformat(a.start) if a.start else end - timedelta(days=365 * 10 - 7)
n = build_index(start, end, api_key())
df = load_index()
print(f"\n今回追加 {n} 件 / 合計 {len(df)} 件 → {INDEX}")
print(df.groupby("docTypeCode").size().rename({"120": "有価証券報告書", "130": "訂正有報", "140": "四半期報告書", "160": "半期報告書"}).to_string())
print(f"銘柄数: {df['code'].nunique()}  期間: {df['submit_date'].min().date()} 〜 {df['submit_date'].max().date()}")
