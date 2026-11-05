"""検証用: 今の銘柄一覧に無い(上場廃止した)会社の財務を EDINET から取る(リポジトリの外に保存。本番では使わない)

J-Quants で上場廃止した銘柄の株価は取れるが、清原式のネットキャッシュ比率には貸借対照表(EDINET)が要るため。
保存先: C:\\Projects\\JP_STOCKS\\data\\delisted\\fundamentals.csv → fund_tidy.csv
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import pandas as pd
from jpstocks import edinet as E
from jpstocks.config import setup_logging

OUT = ROOT.parent / "data" / "delisted"
OUT.mkdir(parents=True, exist_ok=True)
E.FUND, E.FUND_DONE = OUT / "fundamentals.csv", OUT / "fundamentals_done.txt"   # 本番のファイルとは別にする
setup_logging("delisted")
uni = pd.read_csv(ROOT / "data" / "universe.csv", dtype=str)
idx = E.load_index()
idx = idx[idx["docTypeCode"].isin(["120", "130", "160"]) & (idx["withdrawalStatus"].fillna("0") == "0")
          & idx["code"].notna() & ~idx["code"].isin(set(uni["code"])) & (idx["submit_date"] >= "2016-01-01")]
print(f"上場廃止した会社の書類: {len(idx)} 件 / {idx['code'].nunique()} 社")
E.build_fundamentals(idx, E.api_key(), sleep=0.5)
raw = pd.read_csv(E.FUND, dtype=str)
t = E.tidy_fundamentals(raw)
t.to_csv(OUT / "fund_tidy.csv", index=False)
print(f"保存: {OUT / 'fund_tidy.csv'} {len(t)} 書類")
