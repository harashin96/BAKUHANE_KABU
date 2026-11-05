"""STEP 6: カタリストのデータを EDINET から集める(途中で止めても、同じコマンドで続きから再開)

    python scripts/06_fetch_catalyst.py --events      # 書類一覧(大量保有・自社株買い・公開買付)を5年分。約20分
    python scripts/06_fetch_catalyst.py --holders     # 有価証券報告書の大株主の状況(2017年〜、約3.7万件)。10〜14時間
    python scripts/06_fetch_catalyst.py --lvh         # アクティビストの大量保有報告書の中身(config/activists.yaml が必要)と、公開買付の価格
"""
import _bootstrap  # noqa: F401

import argparse
from datetime import date, timedelta

import pandas as pd

from jpstocks import catalyst as C
from jpstocks import edinet as E
from jpstocks.config import setup_logging

ap = argparse.ArgumentParser()
ap.add_argument("--events", action="store_true")
ap.add_argument("--holders", action="store_true")
ap.add_argument("--lvh", action="store_true")
ap.add_argument("--since", default=None, help="書類一覧を取る最初の日(既定: 5年と少し前)")
ap.add_argument("--holders-since", default="2017-01-01")
ap.add_argument("--limit", type=int, default=None)
a = ap.parse_args()

setup_logging("catalyst")
key = E.api_key()
if not C.CODES.exists() and E.INDEX.exists():   # 証券コードと EDINET コードの対応を、手元の書類一覧から作る
    idx = pd.read_csv(E.INDEX, dtype=str).dropna(subset=["edinetCode", "secCode"]).drop_duplicates("edinetCode", keep="last")
    C.save_codes(dict(zip(idx["edinetCode"], idx["secCode"].str[:4])), dict(zip(idx["edinetCode"], idx["filerName"])))
if a.events:
    start = date.fromisoformat(a.since) if a.since else date.today() - timedelta(days=5 * 365 + 5)
    n = C.build_events(start, date.today(), key)
    print(f"書類一覧: {n} 件追加")
if a.holders:
    idx = E.load_index()
    idx = idx[(idx["submit_date"] >= a.holders_since) & (idx["withdrawalStatus"].fillna("0") == "0") & idx["code"].notna()]
    n = C.build_holders(idx, key, limit=a.limit)
    print(f"大株主の状況: {n} 件")
if a.lvh:
    ev = C.load_events()
    n = C.build_lvh(ev, key)
    print(f"アクティビストの大量保有: {n} 件")
    n = C.build_tob(ev, key)
    print(f"公開買付届出書: {n} 件")
