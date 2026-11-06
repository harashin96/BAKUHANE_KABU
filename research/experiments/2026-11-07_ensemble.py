"""期待スコアのモデルを、乱数を変えた複数のモデルの平均(アンサンブル)にすると、成績とぶれはどう変わるか

- M0: 本番と同じ特徴量 / M1: M0 + 決算短信の特徴量(2026-11-07_guide_3m.py)
- 本番は勾配ブースティング1つ(random_state=0)。学習の途中で一部のデータを検証用に取り分けて早めに止める(early stopping)ので、
  取り分け方の乱数で結果が変わる
- 比べるもの: 乱数1つ(10通り) / 5つの平均(0〜4、5〜9 の2組) / 10の平均 / early stopping なし(乱数の影響なし、300回まで学習)
- 選び方: 今の3か月の最終候補(60位以内 × 巻き添え安 × 上位5)と、ランキング上位5
サンプルは C:\\Projects\\JP_STOCKS\\data\\wf_jq_3m.parquet。予測のキャッシュ: wf_jq_3m_ens.parquet
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from jpstocks.jump import RAW

DATA = ROOT.parent / "data"
CACHE = DATA / "wf_jq_3m_ens.parquet"
S = pd.read_parquet(DATA / "wf_jq_3m.parquet")
for c in ["e_rev_up", "e_rev_down"]:
    S[c] = S[c].fillna(0)
base_cols = [c for c in S.columns if c.startswith("r_")] + RAW
earn_cols = ["e_fc_g", "e_guide_up", "e_guide_turn", "e_rev_up", "e_rev_down", "e_q_yoy", "e_q_turn", "e_disc_age"]
SETS = {"M0": base_cols, "M1": base_cols + earn_cols}
P = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=300, l2_regularization=1.0)
NSEED = 10
COST = 0.002
t0 = time.time()

if CACHE.exists():
    T = pd.read_parquet(CACHE)
else:
    dates = pd.DatetimeIndex(sorted(S["date"].unique()))
    out = []
    for Y in range(2019, 2027):
        cut = dates[dates < pd.Timestamp(f"{Y}-01-01")]
        cut = cut[max(0, len(cut) - 14)]
        tr = S[S["date"] < cut].dropna(subset=["exrank"])
        X_te = S[S["date"].dt.year == Y]
        te = X_te[["code", "date", "f3m", "mn3m", "dip"]].copy()
        for name, cols in SETS.items():
            for seed in range(NSEED):
                te[f"{name}_s{seed}"] = HistGradientBoostingRegressor(**P, random_state=seed).fit(tr[cols], tr["exrank"]).predict(X_te[cols])
            m = HistGradientBoostingRegressor(**P, early_stopping=False).fit(tr[cols], tr["exrank"])
            te[f"{name}_noES"] = m.predict(X_te[cols])
        out.append(te)
        print(Y, round(time.time() - t0), flush=True)
    T = pd.concat(out)
    T.to_parquet(CACHE)
T = T[(T["date"] >= "2019-04-01") & T["f3m"].notna()].copy()
for name in SETS:
    s = [f"{name}_s{i}" for i in range(NSEED)]
    T[f"{name}_ens0-4"] = T[s[:5]].mean(axis=1)
    T[f"{name}_ens5-9"] = T[s[5:]].mean(axis=1)
    T[f"{name}_ens10"] = T[s].mean(axis=1)
um = T.groupby("date")["f3m"].mean()


def run(col, kind):
    r = T.groupby("date")[col].rank(ascending=False)
    m = ((r <= 60) & T["dip"]) if kind == "最終候補" else pd.Series(True, index=T.index)
    p = T[m].assign(r=r).sort_values(["date", "r"]).groupby("date").head(5)
    g = p.groupby("date")
    ex = g["f3m"].mean() - COST - um
    return ex, g["f3m"].apply(lambda x: (x > 0).mean()).mean(), g["mn3m"].apply(lambda x: (x <= -0.3).mean()).mean()


def tstat(s, hd=63):
    mm = s.groupby(s.index.to_period("M")).mean()
    return mm.mean() / mm.std() * np.sqrt(len(mm) / max(1, hd / 21))


pd.set_option("display.width", 220); pd.set_option("display.float_format", "{:.2f}".format)
for kind in ["最終候補", "ランキング上位5"]:
    rows, ref = {}, {}
    for name in SETS:
        singles = [run(f"{name}_s{i}", kind)[0] for i in range(NSEED)]
        sm = np.array([s.mean() * 100 for s in singles])
        rows[(name, "乱数1つ(10通りの平均)")] = {"3か月%": sm.mean(), "最小%": sm.min(), "最大%": sm.max(), "ばらつき": sm.std()}
        for v in ["ens0-4", "ens5-9", "ens10", "noES", "s0"]:
            ex, win, crash = run(f"{name}_{v}", kind)
            yr = ex.groupby(ex.index.year).mean() * 100
            rows[(name, v)] = {"3か月%": ex.mean() * 100, "t": tstat(ex), "上がった割合%": win * 100, "途中で-30%以下%": crash * 100,
                               **{str(y): yr[y] for y in yr.index}}
            ref[(name, v)] = ex
    R = pd.DataFrame(rows).T
    print(f"\n===== {kind}(3か月、全銘柄平均との差。s0 = 本番と同じ乱数) =====")
    print(R.to_string())
    d = (ref[("M1", "ens10")] - ref[("M0", "ens10")]).dropna()
    yd = d.groupby(d.index.year).mean()
    print(f"M1 10の平均 − M0 10の平均: {d.mean()*100:+.2f}%  差の t {tstat(d):.2f}  上回った年 {(yd > 0).sum()}/{len(yd)}")
    d = (ref[("M0", "ens10")] - ref[("M0", "s0")]).dropna()
    print(f"M0 10の平均 − M0 本番(s0): {d.mean()*100:+.2f}%  差の t {tstat(d):.2f}")
print("done", round(time.time() - t0))
