"""STEP 4: 書類本体を取得して、主要な経営指標を取り出す

    python scripts/04_fetch_edinet_docs.py --limit 20     # まず20件だけ試す
    python scripts/04_fetch_edinet_docs.py                # 全部(数万件・1件約1〜2秒 → 一晩かかる)
    python scripts/04_fetch_edinet_docs.py --types 120    # 有価証券報告書だけ(約3万件)

途中で止めても(Ctrl+C / PCの電源OFF)、もう一度実行すれば続きから。
終わったら data/edinet/fund_tidy.csv(研究用の整理済みの表)を作る。
"""
import argparse

import _bootstrap  # noqa: F401
import pandas as pd

from jpstocks.config import setup_logging
from jpstocks.data import load_universe
from jpstocks.edinet import EDIR, FUND, api_key, build_fundamentals, load_index, tidy_fundamentals

setup_logging("edinet")
ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=None)
ap.add_argument("--types", default="120,130,140,160")
ap.add_argument("--sleep", type=float, default=1.0)
ap.add_argument("--all-codes", action="store_true", help="universe.csv にない銘柄(上場廃止など)も取得")
a = ap.parse_args()

idx = load_index()
idx = idx[idx["docTypeCode"].isin(a.types.split(","))]
idx = idx[idx["withdrawalStatus"].fillna("0") == "0"]
if not a.all_codes:
    codes = set(load_universe()["code"].astype(str))
    idx = idx[idx["code"].isin(codes)]
idx = idx.sort_values("submit_date", ascending=False)  # 新しい書類から(途中で止めても直近が揃う)
build_fundamentals(idx, api_key(), sleep=a.sleep, limit=a.limit)

raw = pd.read_csv(FUND, dtype=str)
tidy = tidy_fundamentals(raw)
out = EDIR / "fund_tidy.csv"
tidy.to_csv(out, index=False)
print(f"\n整理済み: {len(tidy)} 書類 / {tidy['code'].nunique()} 銘柄 → {out}")
cols = [c for c in ["sales", "net_income", "equity", "eps", "bps", "roe", "dps", "shares"] if c in tidy]
print("取れた割合(%):")
print((tidy[cols].notna().mean() * 100).round(0).to_string())
print(tidy.tail(5).to_string())
