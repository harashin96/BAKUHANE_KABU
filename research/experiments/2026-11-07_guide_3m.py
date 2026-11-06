"""3か月保有で、決算短信(J-Quants)の会社予想・業績の数字が効くか。絞り込みのパターン × 予測モデルの種類

使い方: python research/experiments/2026-11-07_guide_3m.py
- データ: 上場廃止した銘柄も含む J-Quants の株価(配当なし)+ EDINET の財務(jqworld.py)。5営業日おき、2019-04〜
- 基準: 今の3か月の最終候補 = ランキング60位以内 × 巻き添え安 × 期待スコア上位5(本番と同じモデル M0)
- 決算短信の特徴量(開示日の翌営業日の寄り付きで買うので先読みなし):
    fc_g(今期の営業利益の会社予想 ÷ 前期の実績 − 1)、guide_up(10%以上の増益予想)、guide_turn(増益予想に転換)、
    rev_up / rev_down(会社予想を5%以上 上方 / 下方修正、60営業日)、q_yoy(四半期累計の営業利益の前年同期比)、q_turn、
    disc_age(最後の決算短信からの日数)
- モデル(どれも walk-forward: 各年、その年より前に答えが確定したデータだけで学習。目的変数 = 3か月後のリターンの順位):
    M0 本番と同じ(勾配ブースティング、今の特徴量) / M1 M0 + 決算短信の特徴量 / M2 M1 を強めに正則化 /
    M3 線形(リッジ回帰、順位の特徴量) / M4 M3 + 決算短信の特徴量
キャッシュ: C:\\Projects\\JP_STOCKS\\data\\wf_jq_3m.parquet(サンプル)、wf_jq_3m_scores.parquet(スコア)
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
from sklearn.linear_model import Ridge
from jpstocks import jquants as J
from jpstocks import kessan as K
from jpstocks.jump import RAW, cross_section, market_indicators
from jqworld import fwd_prices, make_world

DATA = ROOT.parent / "data"
SAMP, SCORES = DATA / "wf_jq_3m.parquet", DATA / "wf_jq_3m_scores.parquet"
COST = 0.002
t0 = time.time()
log = lambda *a: print(f"[{time.time() - t0:5.0f}s]", *a, flush=True)

# ---------- 1. サンプル(5営業日おき): 特徴量・3か月後のリターン・巻き添え安・決算短信
if SAMP.exists():
    S = pd.read_parquet(SAMP)
    log("samples (cache)", S.shape)
else:
    w, uni = make_world()
    dates, codes = w.elig.index, w.elig.columns
    log("world", w.elig.shape)
    px = fwd_prices(w)
    entry = w.m.adj_open.reindex(dates).shift(-1)
    f3 = px.shift(-63) / entry - 1
    f3 = f3.where(f3.abs() < 30)
    mn = (px[::-1].rolling(63, min_periods=40).min()[::-1].shift(-1) / entry - 1)      # 3か月の途中の最安
    r20 = (market_indicators(w.m)["20日の騰落%"] / 100).reindex(dates)
    # 決算短信
    fins = J.load("fins")
    E = K.earnings_panels(fins, dates, codes)
    f = K.disclosure_features(K.tidy_fins(fins))
    f["rev_down"] = ((f["fc"] <= f["prev_fc"] * 0.95) & (f["prev_fc"] > 0)).astype(float)
    E["rev_down"] = K._daily(f[f["rev_down"] == 1].assign(v=1.0), "v", dates, codes, 60).fillna(0)
    st = f[f["stmt"]].assign(dn=lambda x: x["date"].map(pd.Timestamp.toordinal).astype(float))
    last_disc = K._daily(st, "dn", dates, codes, 130)
    E["disc_age"] = pd.DataFrame(np.asarray([d.toordinal() for d in dates], float)[:, None] - last_disc.to_numpy(), index=dates, columns=codes)
    log("earnings panels", list(E))
    S = []
    for i in range(dates.searchsorted(pd.Timestamp("2017-11-01")), len(dates) - 2, 5):
        X, raw = cross_section(w, i)
        if len(X) < 100:
            continue
        c = X.index
        X["f3m"] = f3.iloc[i].reindex(c).to_numpy()
        X["exrank"] = pd.Series(X["f3m"]).rank(pct=True).to_numpy()
        X["mn3m"] = mn.iloc[i].reindex(c).to_numpy()
        for k in ["NCR", "EY", "RET1M", "AGE"]:
            X["x_" + k] = raw[k].to_numpy()
        X["kiyo"] = ((X["r_NCR"] + X["r_EY"]) / 2).to_numpy()
        X["dip"] = ((raw["EY"] > 0) & (X["kiyo"] >= .7) & (raw["AGE"] >= 20) & (raw["RET1M"] <= r20.iloc[i])).to_numpy()
        for k, v in E.items():
            X["e_" + k] = v.iloc[i].reindex(c).to_numpy()
        X["date"] = dates[i]
        S.append(X)
    S = pd.concat(S).reset_index(names="code")
    S.to_parquet(SAMP)
    log("samples", S.shape)

# ---------- 2. モデル(walk-forward)
base_cols = [c for c in S.columns if c.startswith("r_")] + RAW
earn_cols = ["e_fc_g", "e_guide_up", "e_guide_turn", "e_rev_up", "e_rev_down", "e_q_yoy", "e_q_turn", "e_disc_age"]
for c in ["e_rev_up", "e_rev_down"]:
    S[c] = S[c].fillna(0)
rank_cols = [c for c in S.columns if c.startswith("r_")]
# 線形モデル用: 決算短信の数字も日ごとの順位(0〜1)にして、欠けは0.5
for c in ["e_fc_g", "e_q_yoy", "e_disc_age"]:
    S["rk" + c] = S.groupby("date")[c].rank(pct=True)
lin_earn = ["rke_fc_g", "rke_q_yoy", "rke_disc_age", "e_guide_up", "e_guide_turn", "e_rev_up", "e_rev_down", "e_q_turn"]
HGB = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=300, l2_regularization=1.0, random_state=0)
HGB_REG = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=1000, l2_regularization=5.0, random_state=0)
MODELS = {
    "M0 本番と同じ": ("hgb", base_cols, HGB),
    "M1 M0+決算短信": ("hgb", base_cols + earn_cols, HGB),
    "M2 M1を強めに正則化": ("hgb", base_cols + earn_cols, HGB_REG),
    "M3 線形(順位の特徴量)": ("ridge", rank_cols, None),
    "M4 M3+決算短信": ("ridge", rank_cols + lin_earn, None),
}
if SCORES.exists():
    T = pd.read_parquet(SCORES)
    log("scores (cache)")
else:
    dates = pd.DatetimeIndex(sorted(S["date"].unique()))
    out = []
    for Y in range(2019, 2027):
        cut = dates[dates < pd.Timestamp(f"{Y}-01-01")]
        cut = cut[max(0, len(cut) - 14)]          # 3か月(約13サンプル分)前までに答えが確定したものだけ
        tr = S[(S["date"] < cut)].dropna(subset=["exrank"])
        te = S[S["date"].dt.year == Y].copy()
        for name, (kind, cols, prm) in MODELS.items():
            if kind == "hgb":
                m = HistGradientBoostingRegressor(**prm).fit(tr[cols], tr["exrank"])
                te[name] = m.predict(te[cols])
            else:
                Xtr = tr[cols].astype(float).fillna(0.5)
                m = Ridge(alpha=10.0).fit(Xtr, tr["exrank"])
                te[name] = m.predict(te[cols].astype(float).fillna(0.5))
        out.append(te[["code", "date"] + list(MODELS)])
        log("trained", Y)
    T = pd.concat(out)
    T.to_parquet(SCORES)
keep = ["code", "date", "f3m", "mn3m", "dip", "kiyo", "x_EY", "x_NCR", "x_RET1M"] + [c for c in S.columns if c.startswith("e_")]
T = T.merge(S[keep], on=["code", "date"], how="left")
T = T[(T["date"] >= "2019-04-01") & T["f3m"].notna()]
for m in MODELS:
    T["rk_" + m] = T.groupby("date")[m].rank(ascending=False)
log("ready", T.shape)

# ---------- 3. 絞り込みのパターン
g_either = (T["e_guide_up"] == 1) | (T["e_guide_turn"] == 1)
fresh = T["e_disc_age"] <= 14
PATTERNS = {
    "P0 今の最終候補(60位以内×巻き添え安)": lambda r: (r <= 60) & T["dip"],
    "P1 P0 × 会社予想が増益(どちらか)": lambda r: (r <= 60) & T["dip"] & g_either,
    "P2 P0 × 10%以上の増益予想": lambda r: (r <= 60) & T["dip"] & (T["e_guide_up"] == 1),
    "P3 P0 × 増益予想に転換": lambda r: (r <= 60) & T["dip"] & (T["e_guide_turn"] == 1),
    "P4 P0 から減益予想を除く": lambda r: (r <= 60) & T["dip"] & ~(T["e_fc_g"] < 0),
    "P5 P0 から下方修正(60日)を除く": lambda r: (r <= 60) & T["dip"] & (T["e_rev_down"] != 1),
    "P6 P0 × 上方修正(60日)": lambda r: (r <= 60) & T["dip"] & (T["e_rev_up"] == 1),
    "P7 P0 × 四半期が増益(前年同期比プラス)": lambda r: (r <= 60) & T["dip"] & (T["e_q_yoy"] > 0),
    "P8 100位以内×巻き添え安 × 増益予想(どちらか)": lambda r: (r <= 100) & T["dip"] & g_either,
    "P9 巻き添え安(順位の条件なし) × 増益予想(どちらか)": lambda r: T["dip"] & g_either,
    "P10 ランキング上位5": lambda r: r > 0,
    "P11 ランキング × 増益予想(どちらか)": lambda r: g_either,
    "P12 ランキング × 減益予想と下方修正を除く": lambda r: ~(T["e_fc_g"] < 0) & (T["e_rev_down"] != 1),
    "P13 ランキング × 上方修正(60日)": lambda r: T["e_rev_up"] == 1,
    "P14 決算発表から2週間以内 × 増益予想 × 四半期増益(決算後の上昇)": lambda r: fresh & g_either & (T["e_q_yoy"] > 0),
    "P15 巻き添え安 × 決算発表から2週間以内 × 増益予想": lambda r: T["dip"] & fresh & g_either,
}
PRIORITY = "P16 P0 で増益予想を優先(足りなければ残りで補う)"


def run(model: str, pat: str):
    r = T["rk_" + model]
    if pat == PRIORITY:
        m = ((r <= 60) & T["dip"]).to_numpy()
        g = T[m].assign(tier=lambda x: np.where(g_either[m], 0, 1)).sort_values(["date", "tier", "rk_" + model])
    else:
        g = T[PATTERNS[pat](r).fillna(False).to_numpy()].sort_values(["date", "rk_" + model])
    p = g.groupby("date").head(5)
    um = T.groupby("date")["f3m"].mean()
    d = p.groupby("date").agg(ret=("f3m", "mean"), n=("f3m", "size"), crash=("mn3m", lambda x: (x <= -0.3).mean()),
                              win=("f3m", lambda x: (x > 0).mean()))
    d["ex"] = d["ret"] - COST - um.reindex(d.index)
    return d


def tstat(s, hd=63):
    mm = s.groupby(s.index.to_period("M")).mean()
    return mm.mean() / mm.std() * np.sqrt(len(mm) / max(1, hd / 21)) if len(mm) > 2 else np.nan


rows, yearly = [], {}
base = run("M0 本番と同じ", "P0 今の最終候補(60位以内×巻き添え安)")["ex"]
alld = T["date"].nunique()
for model in MODELS:
    pats = list(PATTERNS) + [PRIORITY] if model in ("M0 本番と同じ", "M1 M0+決算短信") else \
        ["P0 今の最終候補(60位以内×巻き添え安)", "P1 P0 × 会社予想が増益(どちらか)", PRIORITY, "P10 ランキング上位5", "P11 ランキング × 増益予想(どちらか)"]
    for pat in pats:
        d = run(model, pat)
        diff = (d["ex"] - base.reindex(d.index)).dropna()
        yr = d["ex"].groupby(d.index.year).mean() * 100
        yd = diff.groupby(diff.index.year).mean()
        rows.append({"モデル": model, "パターン": pat, "3か月 全銘柄平均との差%": d["ex"].mean() * 100, "t": tstat(d["ex"]),
                     "上がった割合%": d["win"].mean() * 100, "途中で-30%以下%": d["crash"].mean() * 100,
                     "基準との差%": diff.mean() * 100, "差のt": tstat(diff), "基準を上回った年": f"{(yd > 0).sum()}/{len(yd)}",
                     "銘柄数(中央値)": d["n"].median(), "候補がある日%": len(d) / alld * 100, "2026年%": yr.get(2026, np.nan)})
        yearly[(model, pat)] = yr
R = pd.DataFrame(rows)
pd.set_option("display.width", 300); pd.set_option("display.max_colwidth", 60); pd.set_option("display.float_format", "{:.1f}".format)
print("\n===== 3か月保有(手数料 往復0.2% を引いた、全銘柄平均との差。基準 = M0 × P0)=====")
print(R.to_string(index=False))
print("\n===== 年別(全銘柄平均との差%)=====")
Y = pd.DataFrame(yearly).T
Y.index = [f"{a} | {b}" for a, b in Y.index]
print(Y.round(1).to_string())
R.to_csv(DATA / "exp_guide_3m.csv", index=False, encoding="utf-8-sig")
Y.to_csv(DATA / "exp_guide_3m_yearly.csv", encoding="utf-8-sig")
log("done")
