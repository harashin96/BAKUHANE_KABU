"""STEP 2: yfinance で全対象銘柄の日足を取得(2回目以降は差分だけ)

    python scripts/02_fetch_prices.py            # 初回は数十分かかります
    python scripts/02_fetch_prices.py --full     # 最初から取り直す
    python scripts/02_fetch_prices.py --limit 100   # 動作確認用(先頭100銘柄だけ)
"""
import _bootstrap  # noqa: F401

import argparse

from jpstocks.config import load_config, setup_logging
from jpstocks.data import fetch_prices, load_universe

ap = argparse.ArgumentParser()
ap.add_argument("--full", action="store_true")
ap.add_argument("--limit", type=int, default=None)
args = ap.parse_args()

setup_logging("fetch")
cfg = load_config()
u = load_universe()
tickers = u["ticker"].tolist()[: args.limit] if args.limit else u["ticker"].tolist()
d = cfg["data"]
fetch_prices(tickers, d["start"], d["chunk"], d["sleep_sec"], update=not args.full)
