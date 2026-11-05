"""決算短信の「会社予想の増益」で絞ると、基準(清原式 × 期待スコア上位5)より本当に良いか(同じ日どうしの差の t 値)

2026-11-06_catalyst_jq.py のキャッシュ(期待スコア)を使う。上場廃止した銘柄も含む J-Quants の株価(配当なし)。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from jpstocks import jquants as J
from jpstocks import kessan as K
from jqworld import make_world

T = pd.read_parquet(ROOT.parent / "data" / "wf_jq.parquet")
w, _ = make_world()
E = K.earnings_panels(J.load("fins"), w.elig.index, w.elig.columns)
sd = sorted(T["date"].unique())
for k in ["guide_up", "guide_turn", "fc_g"]:
    s = E[k].reindex(sd).stack(future_stack=True).rename(k).rename_axis(["date", "code"]).reset_index()
    T = T.merge(s, on=["date", "code"], how="left")
COST = 0.002
S = {"基準": T["kiyoshi"], "会社予想が10%以上の増益": T["kiyoshi"] & (T["guide_up"] == 1),
     "増益予想に転換": T["kiyoshi"] & (T["guide_turn"] == 1),
     "どちらか": T["kiyoshi"] & ((T["guide_up"] == 1) | (T["guide_turn"] == 1))}
for col, hd, lab in [("f1y", 252, "1年"), ("f2y", 504, "2年")]:
    g = T[(T["date"] >= "2019-04-01") & T[col].notna()]
    um = g.groupby("date")[col].mean()
    R = {}
    for k, s in S.items():
        p = g[s.reindex(g.index).fillna(False)].sort_values("rk").groupby("date").head(5)
        R[k] = p.groupby("date")[col].mean() - COST - um
    base = R.pop("基準")
    print(f"\n== 保有{lab}: 基準 {base.mean()*100:+.1f}%(全銘柄平均との差)")
    for k, r in R.items():
        d = (r - base).dropna()
        mm = d.groupby(d.index.to_period("M")).mean()
        t = mm.mean() / mm.std() * np.sqrt(len(mm) / max(1, hd / 21))
        yr = d.groupby(d.index.year).mean() * 100
        print(f"  {k}: {r.mean()*100:+.1f}%  基準との差 {d.mean()*100:+.1f}%  差のt {t:.2f}  基準を上回った年 {(yr > 0).sum()}/{len(yr)}  年別 {yr.round(1).to_dict()}")
