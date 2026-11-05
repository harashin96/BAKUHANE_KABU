"""割安 × カタリスト × 業績回復 を、上場廃止した銘柄も含むデータ(J-Quants の株価 + EDINET)でやり直す

使い方: python research/experiments/2026-11-06_catalyst_jq.py [A|B]
  A: 2026-11-05_catalyst.py と同じ10パターン(EDINET の業績回復・カタリスト)
  B: 決算短信(J-Quants)の業績回復の10パターン
上場廃止(TOB・MBO・破綻など)の後は、最後の株価のまま持っていたことにする(TOB なら ≒ 買付価格)。
株価は分割だけ調整(配当は含まない)。比べるときは、同じデータの中の基準(清原式 × 期待スコア上位5)と比べる。
期待スコアは walk-forward(各年、その年の初めより前に答えが確定したデータだけで学習)。キャッシュ: C:\\Projects\\JP_STOCKS\\data\\wf_jq.parquet
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from jpstocks import catalyst as C
from jpstocks import jquants as J
from jpstocks import kessan as K
from jpstocks.fundamentals import doc_features, load_splits
from jpstocks.jump import RAW, cross_section
from jqworld import all_tidy, fwd_prices, make_world

MODE = sys.argv[1] if len(sys.argv) > 1 else "A"
CACHE = ROOT.parent / "data" / "wf_jq.parquet"
t0 = time.time()
w, uni = make_world()
dates, codes = w.elig.index, w.elig.columns
print("world", w.elig.shape, round(time.time() - t0), flush=True)

if CACHE.exists():
    T = pd.read_parquet(CACHE)
else:
    px = fwd_prices(w)
    entry = w.m.adj_open.reindex(dates).shift(-1)
    fwd = {}
    for k, h in {"3m": 63, "1y": 252, "2y": 504}.items():
        f = px.shift(-h) / entry - 1
        fwd[k] = f.where(f.abs() < 30)
    S = []
    for i in range(dates.searchsorted(pd.Timestamp("2017-11-01")), len(dates) - 2, 5):
        X, raw = cross_section(w, i)
        if len(X) < 100:
            continue
        c = X.index
        X["exrank"] = fwd["3m"].iloc[i].reindex(c).rank(pct=True).to_numpy()
        for k in fwd:
            X["f" + k] = fwd[k].iloc[i].reindex(c).to_numpy()
        for k in ["NCR", "EY", "BP", "DY", "OIg"]:
            X[k] = raw[k].to_numpy()
        X["kiyo"] = ((X["r_NCR"] + X["r_EY"]) / 2).to_numpy()
        X["date"] = dates[i]
        S.append(X)
    S = pd.concat(S)
    cols = [c for c in S.columns if c.startswith("r_")] + RAW
    P_ = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=300, l2_regularization=1.0, random_state=0)
    out = []
    for Y in range(2019, 2027):
        pos = dates.searchsorted(pd.Timestamp(f"{Y}-01-01"))
        tr = S[S["date"] < dates[max(0, pos - 63 - 2)]].dropna(subset=["exrank"])
        m = HistGradientBoostingRegressor(**P_).fit(tr[cols], tr["exrank"])
        te = S[S["date"].dt.year == Y].copy()
        te["score"] = m.predict(te[cols])
        out.append(te.drop(columns=cols))
    T = pd.concat(out).reset_index(names="code")
    T = T[T.date >= "2019-04-01"]
    T["rk"] = T.groupby("date")["score"].rank(ascending=False)
    T["kiyoshi"] = (T.NCR >= 1) & (T.EY > 0)
    T.to_parquet(CACHE)
print("scores", T.shape, round(time.time() - t0), flush=True)

# 特徴量(5日おきのサンプル日だけ)
sd = sorted(T["date"].unique())
def at(panel):
    return panel.reindex(sd).stack(future_stack=True).rename_axis(["date", "code"])
P = C.catalyst_panels(doc_features(all_tidy(), load_splits()), dates, codes, uni)
E = K.earnings_panels(J.load("fins"), dates, codes)
add = {k: at(v) for k, v in {**P, **E}.items() if k not in ("half_g", "opm_chg")}
A = pd.DataFrame(add).reset_index()
T = T.merge(A, on=["date", "code"], how="left")
prof = T["EY"] > 0
for c in ["NCR", "EY", "BP", "DY"]:
    T.loc[prof, "v_" + c] = T[prof].groupby("date")[c].rank(pct=True)
T["vscore"] = T[["v_NCR", "v_EY", "v_BP", "v_DY"]].mean(axis=1)       # 割安総合: 4つの順位の平均(黒字のみ)
T["value30"] = T.groupby("date")["vscore"].rank(pct=True) >= 0.7
T["recov_now"] = (T["room_x"] <= 0.6) & (T["OIg"] > 0)
T["recovery"] = (T["op_turn"] == 1) | (T["loss_turn"] == 1) | T["recov_now"] | (T["margin_up"] == 1)
cat_cols = [c for c in ["buyback", "div_up", "new5", "act_new", "act_hold", "parent", "owner"] if c in T]
T["catalyst"] = (T[cat_cols] == 1).any(axis=1)
T["delisted_later"] = ~T["code"].isin(set(w.m.adj_close.columns[w.m.adj_close.iloc[-5:].notna().any()]))
print("merged", T.shape, round(time.time() - t0), flush=True)

K_ = T["kiyoshi"]
one = lambda c: (T[c] == 1) if c in T else pd.Series(False, index=T.index)
if MODE == "A":
    PATTERNS = {
        "0 基準: 清原式 × 期待スコア上位5": K_,
        "1 清原式 × 減益→増益": K_ & one("op_turn"),
        "2 清原式 × 回復の途中(過去最高の6割以下で増益)": K_ & T["recov_now"],
        "3 清原式 × 営業利益率が2pt以上改善": K_ & one("margin_up"),
        "4 清原式 × 自社株買い or 増配": K_ & (one("buyback") | one("div_up")),
        "5 清原式 × 親子上場 or オーナー企業": K_ & (one("parent") | one("owner")),
        "6 清原式 × アクティビスト(新規 or 保有中)": K_ & (one("act_new") | one("act_hold")),
        "7 清原式 × 新規5%超(アクティビスト以外)": K_ & one("new5"),
        "8 清原式 × 業績回復 × カタリスト": K_ & T["recovery"] & T["catalyst"],
        "9 割安総合上位30% × 回復の余地大 × 減益→増益": T["value30"] & (T["room_x"] <= 0.6) & one("op_turn"),
    }
else:
    PATTERNS = {
        "0 基準: 清原式 × 期待スコア上位5": K_,
        "1 清原式 × 上方修正(60営業日以内)": K_ & one("rev_up"),
        "2 清原式 × 会社予想が10%以上の増益": K_ & one("guide_up"),
        "3 清原式 × 増益予想に転換(前期は減益)": K_ & one("guide_turn"),
        "4 清原式 × 四半期の増益転換": K_ & one("q_turn"),
        "5 清原式 × (上方修正 or 四半期の増益転換) × カタリスト": K_ & (one("rev_up") | one("q_turn")) & T["catalyst"],
        "6 清原式 × 回復の余地大 × 増益予想に転換": K_ & (T["room_x"] <= 0.6) & one("guide_turn"),
        "7 割安総合上位30% × 上方修正": T["value30"] & one("rev_up"),
        "8 割安総合上位30% × 増益予想に転換": T["value30"] & one("guide_turn"),
        "9 割安総合上位30% × 四半期の増益転換 × 回復の余地大": T["value30"] & one("q_turn") & (T["room_x"] <= 0.6),
    }

HS = {"1年": ("f1y", 252), "2年": ("f2y", 504)}
COST = 0.002   # 往復の手数料・スリッページ(片道0.1%)


def stats(sel, start, h):
    col, hd = HS[h]
    g = T[(T["date"] >= start) & T[col].notna()]
    m = sel.reindex(g.index).fillna(False)
    pick = g[m].sort_values("rk").groupby("date").head(5)
    if pick.empty:
        return None
    uni_mean = g.groupby("date")[col].mean()
    d = pick.groupby("date").agg(r=(col, "mean"))
    d["ex"] = d["r"] - COST - uni_mean.reindex(d.index)
    mm = d.groupby(d.index.to_period("M"))["ex"].mean()
    t = mm.mean() / mm.std() * np.sqrt(len(mm) / max(1, hd / 21)) if len(mm) > 2 else np.nan
    cnt = m[m].groupby(g.loc[m[m].index, "date"]).size()
    v = pick[col] - COST
    return {"全銘柄平均との差%": d["ex"].mean() * 100, "t": t, "上がった%": (v > 0).mean() * 100, "+50%以上%": (v >= .5).mean() * 100,
            "2倍以上%": (v >= 1).mean() * 100, "-30%以下%": (v <= -.3).mean() * 100, "該当銘柄数(中央値)": cnt.median(),
            "選べた日の割合%": len(d) / g["date"].nunique() * 100, "上場廃止した銘柄%": pick["delisted_later"].mean() * 100,
            "年別": (d["ex"].groupby(d.index.year).mean() * 100).round(1).to_dict(), "期間": f"{d.index.min():%Y-%m}〜{d.index.max():%Y-%m}"}


pd.set_option("display.width", 260); pd.set_option("display.float_format", "{:.1f}".format); pd.set_option("display.max_colwidth", 80)
for start, lab in [("2019-04-01", "全期間(2019-04〜)"), ("2021-11-05", "大量保有のデータがある期間(2021-11〜)")]:
    for h in HS:
        rows = {k: stats(s, start, h) for k, s in PATTERNS.items()}
        R = pd.DataFrame({k: v for k, v in rows.items() if v}).T
        print(f"\n===== {MODE} {lab} 保有{h}(5日おき、上位5銘柄、手数料込み) =====")
        print(R.drop(columns=["年別"]).to_string())
        print("年別(全銘柄平均との差%):")
        for k, v in R["年別"].items():
            print(f"  {k}: {v}")
print("done", round(time.time() - t0))
