"""2026-11-07_guide_3m.py の確認: M1(本番のモデル + 決算短信の特徴量)が M0 より良かったのは、学習の乱数のせいではないか

勾配ブースティングは、学習の途中で一部のデータを検証用に取り分けて早めに止める(取り分け方が乱数で変わる)。
乱数を5通り変えて M0 と M1 を学習し直し、今の最終候補の選び方(60位以内 × 巻き添え安 × 上位5)の成績を比べる。
サンプルは 2026-11-07_guide_3m.py のキャッシュ(C:\\Projects\\JP_STOCKS\\data\\wf_jq_3m.parquet)を使う。
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
S = pd.read_parquet(DATA / "wf_jq_3m.parquet")
for c in ["e_rev_up", "e_rev_down"]:
    S[c] = S[c].fillna(0)
base_cols = [c for c in S.columns if c.startswith("r_")] + RAW
earn_cols = ["e_fc_g", "e_guide_up", "e_guide_turn", "e_rev_up", "e_rev_down", "e_q_yoy", "e_q_turn", "e_disc_age"]
SETS = {"M0": base_cols, "M1": base_cols + earn_cols}
COST = 0.002
t0 = time.time()
dates = pd.DatetimeIndex(sorted(S["date"].unique()))
out = []
for Y in range(2019, 2027):
    cut = dates[dates < pd.Timestamp(f"{Y}-01-01")]
    cut = cut[max(0, len(cut) - 14)]
    tr = S[S["date"] < cut].dropna(subset=["exrank"])
    te = S[S["date"].dt.year == Y][["code", "date", "f3m", "dip"]].copy()
    X_te = S[S["date"].dt.year == Y]
    for name, cols in SETS.items():
        for seed in range(5):
            m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=300,
                                              l2_regularization=1.0, random_state=seed).fit(tr[cols], tr["exrank"])
            te[f"{name}_s{seed}"] = m.predict(X_te[cols])
    out.append(te)
    print(Y, round(time.time() - t0), flush=True)
T = pd.concat(out)
T = T[(T["date"] >= "2019-04-01") & T["f3m"].notna()]
um = T.groupby("date")["f3m"].mean()


def res(col):
    r = T.groupby("date")[col].rank(ascending=False)
    p = T[(r <= 60) & T["dip"]].assign(r=r).sort_values(["date", "r"]).groupby("date").head(5)
    ex = p.groupby("date")["f3m"].mean() - COST - um
    return ex


rows = {}
for name in SETS:
    for seed in range(5):
        ex = res(f"{name}_s{seed}")
        rows[(name, seed)] = {"全銘柄平均との差%": ex.mean() * 100, **{str(y): v * 100 for y, v in ex.groupby(ex.index.year).mean().items()}}
R = pd.DataFrame(rows).T
pd.set_option("display.width", 200); pd.set_option("display.float_format", "{:.1f}".format)
print(R.to_string())
print("\n平均:", R.groupby(level=0)["全銘柄平均との差%"].mean().round(2).to_dict(), " ばらつき(標準偏差):", R.groupby(level=0)["全銘柄平均との差%"].std().round(2).to_dict())
d = R.loc["M1", "全銘柄平均との差%"].to_numpy() - R.loc["M0", "全銘柄平均との差%"].to_numpy()
print("同じ乱数どうしの差 M1 − M0:", np.round(d, 2), " M1 が上回った乱数:", int((d > 0).sum()), "/ 5")
