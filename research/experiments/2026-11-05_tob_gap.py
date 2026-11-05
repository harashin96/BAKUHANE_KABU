"""TOB(公開買付)で上場廃止になった会社が、検証からどれくらい抜けているか

株価データ(yfinance)は今上場している会社だけなので、TOB で上場廃止になった「当たり」の銘柄は株価の履歴ごと検証から消えている。
EDINET の公開買付届出書(240、2021-11 以降)の対象の会社のうち、今の銘柄一覧に無い会社を数え、
TOB の直前の有価証券報告書の財務と買付価格から「清原式(ネットキャッシュ比率1以上の黒字)に当てはまっていたか」を調べる。
TOB 直前の株価は無いので、買付価格 ÷ 1.4(プレミアム40%と仮定)を直前の株価の目安にする。

使い方: python research/experiments/2026-11-05_tob_gap.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from jpstocks import catalyst as C
from jpstocks import edinet as E

PREMIUM = 1.4
uni = pd.read_csv(ROOT / "data" / "universe.csv", dtype=str)
ev = C.load_events()
tob = pd.read_csv(C.TOB, dtype={"target": str})
tob["submit_date"] = pd.to_datetime(tob["submit_date"])
t = tob.dropna(subset=["target"]).sort_values("submit_date").drop_duplicates("target")      # 会社ごとに最初の TOB
# 自社株の公開買付(届出者 = 対象の会社)は除く
self_tob = ev[ev["docTypeCode"] == "240"].set_index("docID")["secCode"].str[:4]
t = t[t["docID"].map(self_tob).fillna("") != t["target"]]
t["listed_now"] = t["target"].isin(uni["code"])
print(f"公開買付の対象(自社株TOBを除く、{t.submit_date.min():%Y-%m}〜{t.submit_date.max():%Y-%m}): {len(t)} 社 / うち今の銘柄一覧に無い(上場廃止) {(~t.listed_now).sum()} 社")
print("年別(上場廃止):", t[~t.listed_now].groupby(t.submit_date.dt.year).size().to_dict())
print(f"買付価格を読み取れた: {t['price'].notna().sum()} / {len(t)}")

# 上場廃止になった会社の、TOB 直前の有価証券報告書・半期報告書の財務
idx = E.load_index()
idx = idx[idx["docTypeCode"].isin(["120", "130", "160"])]
key = E.api_key()
gone = t[~t.listed_now & t["price"].notna()]
rows = []
for r in gone.itertuples():
    d = idx[(idx["code"] == r.target) & (idx["submit_date"] < r.submit_date)].sort_values("submit_date")
    if d.empty:
        continue
    doc = d.iloc[-1].to_dict()
    try:
        raw = E.fetch_document(doc, key)
    except Exception:
        continue
    if not raw:
        continue
    x = E.tidy_fundamentals(pd.DataFrame([{**z, "docID": doc["docID"], "code": doc["code"], "docTypeCode": doc["docTypeCode"],
                                            "submit_date": str(doc["submit_date"])[:10], "periodEnd": doc.get("periodEnd")} for z in raw]).astype(str))
    if x.empty:
        continue
    x = x.iloc[0]
    g = lambda k: x[k] if k in x and pd.notna(x[k]) else np.nan
    shares = (g("shares_filing") if pd.notna(g("shares_filing")) else g("shares")) - (g("treasury") if pd.notna(g("treasury")) else 0)
    net_cash = g("current_assets") + 0.7 * (g("inv_securities") if pd.notna(g("inv_securities")) else 0) - g("liabilities")
    rows.append({"code": r.target, "date": r.submit_date, "price": r.price, "shares": shares, "net_cash": net_cash,
                 "net_income": g("net_income"), "equity": g("equity"), "doc": doc["docTypeCode"]})
    time.sleep(0.5)
G = pd.DataFrame(rows)
G["mcap_pre"] = G["price"] / PREMIUM * G["shares"]
G["NCR_pre"] = G["net_cash"] / G["mcap_pre"]
G["PBR_pre"] = G["mcap_pre"] / G["equity"]
G["kiyohara_pre"] = (G["NCR_pre"] >= 1) & (G["net_income"] > 0)
print(f"\n財務を取れた上場廃止の会社: {len(G)} 社")
print(f"TOB 直前(買付価格÷{PREMIUM})で清原式に当てはまっていた: {G['kiyohara_pre'].sum()} 社({G['kiyohara_pre'].mean()*100:.0f}%)")
print(f"同じく PBR 1倍未満: {(G['PBR_pre'] < 1).sum()} 社 / ネットキャッシュ比率の中央値 {G['NCR_pre'].median():.2f}")
print("年別 清原式に当てはまっていた社数:", G[G.kiyohara_pre].groupby(G.date.dt.year).size().to_dict())

# 今の清原式の銘柄数(1日あたり)と比べて、1年で何%が TOB で抜けたか
wf = ROOT.parent / "data" / "wf_scores_kiyo.parquet"
if wf.exists():
    T = pd.read_parquet(wf, columns=["date", "kiyoshi"])
    n = T[T.date >= "2022-01-01"].groupby("date")["kiyoshi"].sum().median()
    per_year = G["kiyohara_pre"].sum() / ((G.date.max() - G.date.min()).days / 365)
    print(f"\n清原式の銘柄数(2022年以降、1日あたりの中央値): {n:.0f} / TOB で抜けた清原式の会社: 年 {per_year:.1f} 社 "
          f"→ 清原式の銘柄の 約{per_year / (n + per_year) * 100:.1f}% が毎年 TOB で消えている")
    print(f"   プレミアム40%なら、清原式を全部持った場合の1年リターンを 約{per_year / (n + per_year) * 40:.1f}% 低く見せている(上限の目安)")
G.to_csv(ROOT.parent / "data" / "tob_gap.csv", index=False)
