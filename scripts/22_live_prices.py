"""場中の株価だけを更新する(ランキングは作り直さない)。GitHub Actions の live.yml から実行

    python scripts/22_live_prices.py --site https://<ユーザー名>.github.io/<リポジトリ名>/ --out site

公開中のページ(index.html など)をそのまま取ってきて、ランキング上位の銘柄の今の株価を live.json に書く。
ページ側は live.json を読んで「株価」と「ランクイン後」の列だけ差し替える。
順位・確率はモデルを学習・検証したときと同じく、前の営業日の終値で計算したまま。
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

FILES = ["index.html", "stocks.json", "ranking.csv", "top.json"]   # 毎日のランキング作成(ranking.yml)が公開するファイル

ap = argparse.ArgumentParser()
ap.add_argument("--site", required=True)
ap.add_argument("--out", default="site")
a = ap.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
base = a.site.rstrip("/") + "/"

for f in FILES:
    r = requests.get(base + f, timeout=30)
    if r.status_code != 200:
        print(f"{f} を取得できません({r.status_code})。毎日のランキング作成が一度終わるまで待ちます")
        sys.exit(2)
    (out / f).write_bytes(r.content)
(out / ".nojekyll").touch()

top = json.loads((out / "top.json").read_text(encoding="utf-8"))
codes = [s["code"] for s in top["stocks"]]
# 5分足の最後の値 = 今の株価(約20分遅れ)。休日・場が開く前は前の営業日の最後の値になる
df = yf.download([c + ".T" for c in codes], period="5d", interval="5m", progress=False, auto_adjust=False, threads=True)
close = df["Close"].dropna(how="all")
if close.empty:
    print("株価を取得できませんでした")
    sys.exit(1)
last = close.ffill().iloc[-1]
asof = close.index[-1]
asof = (asof.tz_convert("Asia/Tokyo") if asof.tzinfo else asof.tz_localize("Asia/Tokyo")) + pd.Timedelta(minutes=5)
prices = {t.replace(".T", ""): round(float(v), 2) for t, v in last.items() if pd.notna(v)}
(out / "live.json").write_text(json.dumps({"asof": asof.strftime("%Y-%m-%dT%H:%M"), "ranking_date": top["date"],
                                           "prices": prices}, ensure_ascii=False), encoding="utf-8")
print(f"{asof:%Y-%m-%d %H:%M} 時点の株価: {len(prices)}/{len(codes)} 銘柄")
