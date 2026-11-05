"""割安 × カタリスト × 業績回復: 清原式(と割安総合)の銘柄を、業績回復・カタリストの条件で絞ると、1〜2年後の成績が上がるか

使い方: python research/experiments/2026-11-05_catalyst.py [walk-forward の期待スコアのキャッシュ.parquet]
  キャッシュが無ければ template_walkforward.py で作る(30〜40分)。
比較の基準: 長期の最終候補 = 清原式(ネットキャッシュ比率1以上の黒字)× 期待スコア上位5。どのパターンも「条件を満たす銘柄のうち期待スコア上位5」を5日おきに選ぶ。
業績回復・カタリストの数字は、どれも書類の提出日以降の取引日にだけ使う(jpstocks/catalyst.py)。
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from jpstocks import catalyst as C
from jpstocks.data import load_prices, load_universe
from jpstocks.fundamentals import doc_features, load_splits, load_tidy
from jpstocks.jump import build_world

t0 = time.time()
cache = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "data" / "wf_scores_kiyo.parquet"   # リポジトリの外(大きいので)
if not cache.exists():
    subprocess.run([sys.executable, str(ROOT / "research" / "experiments" / "template_walkforward.py"), str(cache)], check=True)
T = pd.read_parquet(cache)
T.columns = [c.replace("f_1年", "f1y").replace("f_2年", "f2y") for c in T.columns]
HS = {"1年": ("f1y", 252), "2年": ("f2y", 504)}

uni = load_universe()
w = build_world(load_prices(), uni, since="2016-10-01")
dates, codes = w.elig.index, w.elig.columns
f = doc_features(load_tidy(), load_splits())
P = C.catalyst_panels(f, dates, codes, uni)
print("panels", sorted(P), round(time.time() - t0), flush=True)

# 5日おきのサンプル日だけ、特徴量を縦長にして T に付ける
sd = sorted(T["date"].unique())
def at(panel):
    return panel.reindex(sd).stack(future_stack=True).rename_axis(["date", "code"])
add = {k: at(P[k]) for k in ["op_turn", "loss_turn", "room_x", "margin_up", "buyback", "div_up", "new5", "act_new", "act_hold", "act_up", "parent", "owner"] if k in P}
for k in ["OIg", "BP", "DY"]:
    add[k] = at(w.feat[k])
A = pd.DataFrame(add).reset_index()
T = T.merge(A, on=["date", "code"], how="left")
# 割安総合: ネットキャッシュ比率・益利回り・純資産倍率の逆数・配当利回りの順位の平均(黒字のみ、その日の中で)
prof = T["EY"] > 0
for c in ["NCR", "EY", "BP", "DY"]:
    T.loc[prof, "v_" + c] = T[prof].groupby("date")[c].rank(pct=True)
T["vscore"] = T[["v_NCR", "v_EY", "v_BP", "v_DY"]].mean(axis=1)
T["value30"] = T.groupby("date")["vscore"].rank(pct=True) >= 0.7
T["recov_now"] = (T["room_x"] <= 0.6) & (T["OIg"] > 0)      # 営業利益が過去5年の最高の6割以下で、増益(元の水準に戻る途中)
T["recovery"] = (T["op_turn"] == 1) | (T["loss_turn"] == 1) | T["recov_now"] | (T["margin_up"] == 1)
cat_cols = [c for c in ["buyback", "div_up", "new5", "act_new", "act_hold", "parent", "owner"] if c in T]
T["catalyst"] = (T[cat_cols] == 1).any(axis=1)
print("merged", T.shape, round(time.time() - t0), flush=True)

K = T["kiyoshi"]
PATTERNS = {
    "0 基準: 清原式 × 期待スコア上位5": K,
    "1 清原式 × 減益→増益": K & (T["op_turn"] == 1),
    "2 清原式 × 回復の途中(過去最高の6割以下で増益)": K & T["recov_now"],
    "3 清原式 × 営業利益率が2pt以上改善": K & (T["margin_up"] == 1),
    "4 清原式 × 自社株買い or 増配": K & ((T["buyback"] == 1) | (T["div_up"] == 1)),
    "5 清原式 × 親子上場 or オーナー企業": K & ((T.get("parent") == 1) | (T.get("owner") == 1)),
    "6 清原式 × アクティビスト(新規 or 保有中)": K & ((T["act_new"] == 1) | (T["act_hold"] == 1)),
    "7 清原式 × 新規5%超(アクティビスト以外)": K & (T["new5"] == 1),
    "8 清原式 × 業績回復 × カタリスト": K & T["recovery"] & T["catalyst"],
    "9 割安総合上位30% × 回復の余地大 × 減益→増益": T["value30"] & (T["room_x"] <= 0.6) & (T["op_turn"] == 1),
}


def stats(sel, start, h):
    col, hd = HS[h]
    g = T[(T["date"] >= start) & T[col].notna()]
    m = sel.reindex(g.index).fillna(False)
    pick = g[m].sort_values("rk").groupby("date").head(5)
    if pick.empty:
        return None
    uni_mean = g.groupby("date")[col].mean()
    d = pick.groupby("date").agg(r=(col, "mean"), n=(col, "size"))
    d["ex"] = d["r"] - uni_mean.reindex(d.index)
    mm = d.groupby(d.index.to_period("M"))["ex"].mean()
    t = mm.mean() / mm.std() * np.sqrt(len(mm) / max(1, hd / 21)) if len(mm) > 2 else np.nan
    cnt = m[m].groupby(g.loc[m[m].index, "date"]).size()
    v = pick[col]
    return {"全銘柄平均との差%": d["ex"].mean() * 100, "t": t, "上がった%": (v > 0).mean() * 100, "+50%以上%": (v >= .5).mean() * 100,
            "2倍以上%": (v >= 1).mean() * 100, "-30%以下%": (v <= -.3).mean() * 100, "該当銘柄数(中央値)": cnt.median(),
            "選べた日の割合%": len(d) / g["date"].nunique() * 100, "年別": (d["ex"].groupby(d.index.year).mean() * 100).round(1).to_dict(),
            "期間": f"{d.index.min():%Y-%m}〜{d.index.max():%Y-%m}"}


pd.set_option("display.width", 250); pd.set_option("display.float_format", "{:.1f}".format); pd.set_option("display.max_colwidth", 80)
for start, lab in [("2019-04-01", "全期間(2019-04〜)"), ("2021-11-05", "大量保有のデータがある期間(2021-11〜)")]:
    for h in HS:
        rows = {k: stats(s, start, h) for k, s in PATTERNS.items()}
        R = pd.DataFrame({k: v for k, v in rows.items() if v}).T
        print(f"\n===== {lab} 保有{h}(5日おき、上位5銘柄) =====")
        print(R.drop(columns=["年別"]).to_string())
        print("年別(全銘柄平均との差%):")
        for k, v in R["年別"].items():
            print(f"  {k}: {v}")
T.drop(columns=[c for c in T.columns if c.startswith("v_")]).to_parquet(ROOT.parent / "data" / "wf_catalyst.parquet")
print("done", round(time.time() - t0))
