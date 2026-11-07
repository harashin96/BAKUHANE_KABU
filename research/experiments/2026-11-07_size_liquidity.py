"""【弱点の調査】3か月の最終候補は、規模(時価総額)・流動性(売買代金)・業種・値動きの大きさで成績が変わるか。2026年に負けている理由

- データ: 上場廃止を含む J-Quants(jqworld.py)。予測は 2026-11-07_ensemble.py のキャッシュ(walk-forward、M0 = 本番と同じ特徴量)
  - s0: 本番と同じ乱数のモデル1つ / ens10: 乱数10通りの平均(乱数のぶれを除いた参考)
- 基準: ランキング60位以内 × 巻き添え安 × 期待スコア上位5、翌営業日の寄り付きで買い63営業日後に売る、往復0.2%
- 売買代金は J-Quants の Va(当日の売買代金)の20営業日の中央値(その日の引けまでに分かる値)
- 試すパターン(閾値は先に決めたもの。過去の成績を見て選んでいない):
  P1 売買代金1億円以上だけ / P2 時価総額100億円以上だけ / P3 その日の対象銘柄で時価総額が下位20%の銘柄を除く
  P4 同じ業種(17業種)は2銘柄まで / P5 同じ業種は1銘柄まで / P6 値動きの大きさの逆数で資金配分 / P7 値動きの大きさ上位20%を除く
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from jpstocks import jquants as J
from jqworld import jq_universe

DATA = ROOT.parent / "data"
COST = 0.002
t0 = time.time()

T = pd.read_parquet(DATA / "wf_jq_3m_ens.parquet")
S = pd.read_parquet(DATA / "wf_jq_3m.parquet", columns=["code", "date", "SIZE", "VOL60", "r_SIZE", "r_VOL60"])
T["ens10"] = T[[f"M0_s{i}" for i in range(10)]].mean(axis=1)
T = T[["code", "date", "f3m", "mn3m", "dip", "M0_s0", "ens10"]].merge(S, on=["code", "date"], how="left")
T = T[(T["date"] >= "2019-04-01") & T["f3m"].notna()].copy()

# 売買代金(20営業日の中央値、億円)
b = J.load("bars", ["Date", "Code", "Va"])
b = b[b["Code"].str.len() == 5]
va = pd.DataFrame({"date": pd.to_datetime(b["Date"]), "code": b["Code"].str[:4], "Va": pd.to_numeric(b["Va"], errors="coerce")})
va = va.drop_duplicates(["code", "date"]).pivot(index="date", columns="code", values="Va").sort_index()
v20 = (va.rolling(20, min_periods=15).median() / 1e8).stack().rename("val_oku").reset_index()
T = T.merge(v20, on=["date", "code"], how="left")
uni = jq_universe()[["code", "sector17", "market"]]
T = T.merge(uni, on="code", how="left")
T["mcap_oku"] = np.exp(T["SIZE"]) / 1e8
print("loaded", len(T), round(time.time() - t0), flush=True)

um = T.groupby("date")["f3m"].mean()
T["ex"] = T["f3m"] - COST - T["date"].map(um)


def tstat(s, hd=63):
    mm = s.groupby(s.index.to_period("M")).mean()
    return mm.mean() / mm.std() * np.sqrt(len(mm) / max(1, hd / 21))


def select(col, pat):
    r = T.groupby("date")[col].rank(ascending=False)
    c = T[(r <= 60) & T["dip"]].assign(r=r)
    if pat == "P1": c = c[c["val_oku"] >= 1]
    if pat == "P2": c = c[c["mcap_oku"] >= 100]
    if pat == "P3": c = c[c["r_SIZE"] > 0.2]
    if pat == "P7": c = c[c["r_VOL60"] <= 0.8]
    c = c.sort_values(["date", "r"])
    if pat in ("P4", "P5"):
        cap = 2 if pat == "P4" else 1
        c = c[c.groupby(["date", "sector17"]).cumcount() < cap]
    p = c.groupby("date").head(5).copy()
    p["w"] = 1.0
    if pat == "P6":
        p["w"] = 1 / p["VOL60"].clip(lower=0.005)
    p["w"] = p["w"] / p.groupby("date")["w"].transform("sum")
    return p


def summarize(p):
    g = p.assign(wex=p["ex"] * p["w"], wwin=(p["f3m"] > 0) * p["w"], wcr=(p["mn3m"] <= -0.3) * p["w"]).groupby("date")
    ex = g["wex"].sum()
    return ex, g["wwin"].sum().mean(), g["wcr"].sum().mean(), g.size().median()


NAMES = {"P0": "基準(60位以内 × 巻き添え安 上位5)", "P1": "売買代金1億円以上だけ", "P2": "時価総額100億円以上だけ",
         "P3": "時価総額 下位20%を除く", "P4": "同じ業種は2銘柄まで", "P5": "同じ業種は1銘柄まで",
         "P6": "値動きの逆数で資金配分", "P7": "値動きの大きさ 上位20%を除く"}
pd.set_option("display.width", 250); pd.set_option("display.float_format", "{:.2f}".format)
base_picks = {}
for col in ["M0_s0", "ens10"]:
    rows, base = {}, None
    for pat, nm in NAMES.items():
        p = select(col, pat)
        if pat == "P0": base_picks[col] = p
        ex, win, cr, n = summarize(p)
        yr = ex.groupby(ex.index.year).mean() * 100
        r = {"3か月%": ex.mean() * 100, "t": tstat(ex), "上がった割合%": win * 100, "途中で-30%以下%": cr * 100, "銘柄数": n,
             "候補がある日%": len(ex) / um.size * 100}
        if base is None:
            base = ex
        else:
            d = (ex - base.reindex(ex.index)).dropna()
            yd = d.groupby(d.index.year).mean()
            r.update({"基準との差": d.mean() * 100, "差のt": tstat(d), "上回った年": f"{(yd > 0).sum()}/{len(yd)}"})
        r.update({str(y): yr[y] for y in yr.index})
        rows[f"{pat} {nm}"] = r
    print(f"\n===== パターン別(モデル {col}、3か月、全銘柄平均との差) =====")
    print(pd.DataFrame(rows).T.to_string())

# ---- 基準の候補を、規模・流動性・業種・値動きで分ける(1銘柄ずつの全銘柄平均との差) ----
for col in ["M0_s0", "ens10"]:
    p = base_picks[col].copy()
    p["year"] = p["date"].dt.year
    p["規模"] = pd.cut(p["mcap_oku"], [0, 50, 100, 300, 1000, 1e9], labels=["~50億", "50~100億", "100~300億", "300~1000億", "1000億~"])
    p["売買代金"] = pd.cut(p["val_oku"], [0, 0.3, 1, 3, 10, 1e9], labels=["~0.3億", "0.3~1億", "1~3億", "3~10億", "10億~"])
    p["値動き"] = pd.cut(p["r_VOL60"], [0, .2, .4, .6, .8, 1.0], labels=["小さい20%", "20~40%", "40~60%", "60~80%", "大きい20%"])
    print(f"\n===== 基準の候補の内訳(モデル {col}) =====")
    for k in ["規模", "売買代金", "値動き", "market", "sector17"]:
        g = p.groupby(k, observed=True)
        tab = pd.DataFrame({"件数の割合%": g.size() / len(p) * 100, "差%": g["ex"].mean() * 100, "上がった%": g["f3m"].apply(lambda x: (x > 0).mean() * 100),
                            "-30%以下%": g["mn3m"].apply(lambda x: (x <= -.3).mean() * 100),
                            "2026年の件数%": p[p.year == 2026].groupby(k, observed=True).size() / max(1, (p.year == 2026).sum()) * 100,
                            "2026年の差%": p[p.year == 2026].groupby(k, observed=True)["ex"].mean() * 100})
        if k == "sector17":
            tab = tab.sort_values("件数の割合%", ascending=False).head(10)
        print(f"-- {k}"); print(tab.round(1).to_string())
    print("年別の 候補の売買代金の中央値(億円):", p.groupby("year")["val_oku"].median().round(2).to_dict())
    print("年別の 候補の時価総額の中央値(億円):", p.groupby("year")["mcap_oku"].median().round(0).to_dict())

# ---- 2026年の診断: 巻き添え安の条件そのもの・上位60位そのものは効いていたか ----
print("\n===== 年別: 条件ごとの全銘柄平均との差%(1銘柄ずつの平均、モデル ens10) =====")
r = T.groupby("date")["ens10"].rank(ascending=False)
T["year"] = T["date"].dt.year
D = pd.DataFrame({
    "巻き添え安(全部)": T[T.dip].groupby("year")["ex"].mean(),
    "上位60位(全部)": T[r <= 60].groupby("year")["ex"].mean(),
    "上位60位 × 巻き添え安": T[(r <= 60) & T.dip].groupby("year")["ex"].mean(),
    "上位60位 × 巻き添え安でない": T[(r <= 60) & ~T.dip].groupby("year")["ex"].mean(),
    "上位300位": T[r <= 300].groupby("year")["ex"].mean(),
}) * 100
D["市場(全銘柄平均の3か月%)"] = um.groupby(um.index.year).mean() * 100
print(D.round(2).to_string())
p = base_picks["M0_s0"]
m26 = p[p.date.dt.year >= 2025].groupby(p.date.dt.to_period("M"))["ex"].mean() * 100
print("\n2025〜2026年 月別(基準 s0、買った月):", m26.round(1).to_dict())
w = p[p.date.dt.year == 2026].nsmallest(10, "ex")[["date", "code", "sector17", "mcap_oku", "val_oku", "f3m", "mn3m"]]
print("2026年 大きく負けた候補:"); print(w.round(2).to_string())
print("done", round(time.time() - t0))
