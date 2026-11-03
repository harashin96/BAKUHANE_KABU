"""【ひな形】清原式 × ランキング(期待スコア, walk-forward) × 巻き添え安 を、保有期間 3か月/6か月/1年/2年 で比べる(5日おき)"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # リポジトリの直下
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from jpstocks.data import load_prices, load_universe
from jpstocks.jump import build_world, cross_section, market_indicators, RAW

t0 = time.time()
w = build_world(load_prices(), load_universe(), since="2016-10-01")
dates = w.elig.index
px = w.m.adj_close.reindex(dates)
entry = w.m.adj_open.reindex(dates).shift(-1)
HS = {"3か月": 63, "6か月": 126, "1年": 252, "2年": 504}
fwd = {}
for k, h in HS.items():
    f = px.shift(-h) / entry - 1
    fwd[k] = f.where(f.abs() < 30)
dd = (px[::-1].rolling(252, min_periods=150).min()[::-1].shift(-1) / entry - 1)
F = market_indicators(w.m)
r20 = (F["20日の騰落%"] / 100).reindex(dates)

S = []
for i in range(dates.searchsorted(pd.Timestamp("2017-08-01")), len(dates) - 2, 5):
    X, raw = cross_section(w, i)
    if len(X) < 100:
        continue
    c = X.index
    X["exrank"] = fwd["3か月"].iloc[i].reindex(c).rank(pct=True).to_numpy()
    for k in HS:
        X["f_" + k] = fwd[k].iloc[i].reindex(c).to_numpy()
    X["dd1y"] = dd.iloc[i].reindex(c).to_numpy()
    X["NCR"] = raw["NCR"].to_numpy(); X["EY"] = raw["EY"].to_numpy()
    X["kiyo"] = ((X["r_NCR"] + X["r_EY"]) / 2).to_numpy()
    X["dip"] = ((raw["EY"] > 0) & (X["kiyo"] >= .7) & (raw["AGE"] >= 20) & (raw["RET1M"] <= r20.iloc[i])).to_numpy()
    X["date"] = dates[i]
    S.append(X)
S = pd.concat(S)
cols = [c for c in S.columns if c.startswith("r_")] + RAW
print("samples", len(S), round(time.time() - t0), flush=True)
P = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=300, l2_regularization=1.0, random_state=0)
out = []
for Y in range(2019, 2027):
    pos = dates.searchsorted(pd.Timestamp(f"{Y}-01-01"))
    tr = S[S["date"] < dates[max(0, pos - 63 - 2)]].dropna(subset=["exrank"])
    m = HistGradientBoostingRegressor(**P).fit(tr[cols], tr["exrank"])
    te = S[S["date"].dt.year == Y].copy()
    te["score"] = m.predict(te[cols])
    out.append(te.drop(columns=cols))
T = pd.concat(out).reset_index(names="code")
T = T[T.date >= "2019-04-01"]
T["rk"] = T.groupby("date")["score"].rank(ascending=False)
T["kiyoshi"] = (T.NCR >= 1) & (T.EY > 0)
if len(sys.argv) > 1: T.to_parquet(sys.argv[1])          # 引数があれば途中結果を保存
print("scored", round(time.time() - t0), flush=True)


def pick(g, kind):
    if kind == "清原式(全部)": return g[g.kiyoshi]
    if kind == "清原式 上位5(割安順)": return g[g.kiyoshi].nlargest(5, "kiyo")
    if kind == "清原式 上位5(期待スコア順)": return g[g.kiyoshi].nsmallest(5, "rk")
    if kind == "清原式 × 巻き添え安 上位5(期待スコア順)": return g[g.kiyoshi & g.dip].nsmallest(5, "rk")
    if kind == "清原式 × ランキング100位以内 上位5": return g[g.kiyoshi & (g.rk <= 100)].nsmallest(5, "rk")
    if kind == "ランキング上位5": return g.nsmallest(5, "rk")
    if kind == "ランキング60位以内 × 巻き添え安 上位5(今の最終候補)": return g[(g.rk <= 60) & g.dip].nsmallest(5, "rk")
    if kind == "割安(清原式の条件なし) 上位5": return g[g.EY > 0].nlargest(5, "kiyo")


KINDS = ["清原式(全部)", "清原式 上位5(割安順)", "清原式 上位5(期待スコア順)", "清原式 × 巻き添え安 上位5(期待スコア順)",
         "清原式 × ランキング100位以内 上位5", "ランキング上位5", "ランキング60位以内 × 巻き添え安 上位5(今の最終候補)"]
rows = []
for d, g in T.groupby("date"):
    for k in KINDS:
        s = pick(g, k)
        if not len(s): continue
        r = {"date": d, "kind": k, "n": len(s)}
        for h in HS:
            u = g["f_" + h].mean()
            v = s["f_" + h]
            r[h + "_ex"] = v.mean() - u; r[h + "_raw"] = v.mean(); r[h + "_win"] = (v > 0).mean(); r[h + "_cnt"] = v.notna().sum()
        r["dd50"] = (s.dd1y <= -.5).mean()
        rows.append(r)
R = pd.DataFrame(rows)
R["month"] = R.date.dt.to_period("M")
pd.set_option("display.width", 250); pd.set_option("display.float_format", "{:.1f}".format)
for h, hd in HS.items():
    tab = {}
    for k in KINDS:
        g = R[(R.kind == k)].dropna(subset=[h + "_ex"])
        g = g[g[h + "_cnt"] > 0]
        if not len(g): continue
        mm = g.groupby("month")[h + "_ex"].mean()
        t = mm.mean() / mm.std() * np.sqrt(len(mm) / max(1, hd / 21))     # 重なりを考慮した t
        tab[k] = {"全銘柄平均との差%": g[h + "_ex"].mean() * 100, "年率換算の差%": ((1 + g[h + "_raw"].mean()) ** (252 / hd) - (1 + (g[h + "_raw"] - g[h + "_ex"]).mean()) ** (252 / hd)) * 100,
                  "t": t, "上がった割合%": g[h + "_win"].mean() * 100, "銘柄数": g.n.median(), "期間": f"{g.date.min():%Y-%m}〜{g.date.max():%Y-%m}"}
    print(f"\n===== 保有 {h} =====")
    print(pd.DataFrame(tab).T.to_string())
print("\n1年保有の年別(全銘柄平均との差%)")
y = R.dropna(subset=["1年_ex"]).pivot_table(index=R.date.dt.year, columns="kind", values="1年_ex", aggfunc="mean") * 100
print(y[[k for k in KINDS if k in y.columns]].round(1).T.to_string())
print("\n1年以内に途中で-50%以下になった割合%:", (R.groupby("kind").dd50.mean() * 100).round(1).to_dict())
