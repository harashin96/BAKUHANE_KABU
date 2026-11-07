"""検証台: モデルの案(チャレンジャー)を、どれも同じ方法で採点して leaderboard.csv に並べる

使い方(週1回の研究タスク research/improve_prompt.md から):
    import sys; sys.path.insert(0, "research/lab"); import lab
    S = lab.samples()                                   # 5営業日おきのサンプル(上場廃止を含む J-Quants の株価、配当なし)
    lab.predict("M1_ens10", lab.BASE + lab.EARN)        # walk-forward で予測(乱数10通りの平均)。結果はキャッシュ
    lab.record("M1_ens10", "M0 + 決算短信の特徴量")      # 採点して leaderboard.csv に1行(同じ名前は上書き)
    python research/lab/lab.py                          # 一覧を表示

採点の決まり(すべての案で同じ):
- walk-forward: 各年(2019〜2026)のモデルは、その年より約3か月前までに答えが確定したサンプルだけで学習
- 選び方 final = 今の3か月の最終候補(期待スコア60位以内 × 巻き添え安 × 上位5)/ top5 = ランキング上位5
- 3か月後のリターン − 往復の手数料0.2% − 同じ日の全銘柄平均。2019-04 以降
- 比べる相手(REF)= 今の本番と同じ特徴量のモデルを乱数10通りで平均したもの(本番の乱数の運を除いた実力)
- 新しい特徴量は add_features() で data/lab/features/ に保存してから predict() の cols に入れる

本番に入れる条件(昇格ゲート、research/lab/README.md): 過去の検証で REF との差の t ≥ required_t(試した案の数)、
8年中6年以上で REF を上回る、さらに本番と並走させた成績(shadow)が3か月以上 チャンピオン以上。昇格は利用者の承認が必要。
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd

DATA = ROOT.parent / "data"
LAB = DATA / "lab"
PRED, FEAT = LAB / "preds", LAB / "features"
BOARD = HERE / "leaderboard.csv"
SAMPLES = DATA / "wf_jq_3m.parquet"   # research/experiments/2026-11-07_guide_3m.py が作る
HGB = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=300, l2_regularization=1.0)
COST = 0.002
REF = "M0_ens10"
YEARS = range(2019, 2027)
RAW = ["VOL60", "SIZE", "MAXRET20"]
EARN = ["e_fc_g", "e_guide_up", "e_guide_turn", "e_rev_up", "e_rev_down", "e_q_yoy", "e_q_turn", "e_disc_age"]
_S: pd.DataFrame | None = None


def samples(reload: bool = False) -> pd.DataFrame:
    """サンプル(code, date, 特徴量, f3m=3か月後のリターン, exrank=その日の中での順位, mn3m=途中の最安, dip=巻き添え安)
    + data/lab/features/*.parquet の追加の特徴量(code, date で結合)"""
    global _S
    if _S is not None and not reload:
        return _S
    S = pd.read_parquet(SAMPLES)
    for c in ["e_rev_up", "e_rev_down"]:
        S[c] = S[c].fillna(0)
    for p in sorted(FEAT.glob("*.parquet")) if FEAT.exists() else []:
        f = pd.read_parquet(p)
        S = S.merge(f, on=["code", "date"], how="left", suffixes=("", "_dup"))
        S = S.drop(columns=[c for c in S.columns if c.endswith("_dup")])
    _S = S
    return S


def _base() -> list[str]:
    if not SAMPLES.exists():
        return []
    import pyarrow.parquet as pq
    return [c for c in pq.read_schema(SAMPLES).names if c.startswith("r_")] + RAW


BASE = _base()   # 今の本番と同じ特徴量(順位30個 + 生の値3個)


def add_features(df: pd.DataFrame, name: str):
    """新しい特徴量(列: code, date, 特徴量…)を保存。その日までに分かる情報だけで作ること(先読みしない)"""
    FEAT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(FEAT / f"{name}.parquet")
    samples(reload=True)


def _cut(dates: pd.DatetimeIndex, Y: int):
    c = dates[dates < pd.Timestamp(f"{Y}-01-01")]
    return c[max(0, len(c) - 14)]          # 3か月(約13サンプル分)前までに答えが確定したものだけ


def predict(name: str, cols: list[str], params: dict | None = None, seeds: int = 10, make=None,
            target: str = "exrank", force: bool = False) -> pd.DataFrame:
    """walk-forward の予測(乱数 seeds 通りの平均)。make(seed) で別のモデル(fit/predict を持つもの)も使える。
    キャッシュ: data/lab/preds/<name>.parquet(force=True で作り直し)"""
    p = PRED / f"{name}.parquet"
    if p.exists() and not force:
        return pd.read_parquet(p)
    from sklearn.ensemble import HistGradientBoostingRegressor
    S = samples()
    prm = {**HGB, **(params or {})}
    make = make or (lambda s: HistGradientBoostingRegressor(**prm, random_state=s))
    dates = pd.DatetimeIndex(sorted(S["date"].unique()))
    out = []
    for Y in YEARS:
        tr = S[S["date"] < _cut(dates, Y)].dropna(subset=[target])
        te = S[S["date"].dt.year == Y]
        pr = np.mean([make(s).fit(tr[cols], tr[target]).predict(te[cols]) for s in range(seeds)], axis=0)
        out.append(pd.DataFrame({"code": te["code"].to_numpy(), "date": te["date"].to_numpy(), "score": pr}))
        print(f"  {name} {Y}", flush=True)
    T = pd.concat(out, ignore_index=True)
    PRED.mkdir(parents=True, exist_ok=True)
    T.to_parquet(p)
    return T


def _t(s: pd.Series, hd: int = 63) -> float:
    """重なり(3か月持つので毎月の結果が互いに似る)を考えた t 値"""
    mm = s.groupby(s.index.to_period("M")).mean()
    return float(mm.mean() / mm.std() * np.sqrt(len(mm) / max(1, hd / 21))) if len(mm) > 2 else np.nan


def picks(name: str, kind: str = "final", n: int = 5, top: int = 60) -> pd.DataFrame:
    S = samples()[["code", "date", "f3m", "mn3m", "dip"]]
    p = PRED / f"{name}.parquet"
    if not p.exists():
        raise FileNotFoundError(f"先に predict('{name}', cols) を実行してください")
    T = pd.read_parquet(p).merge(S, on=["code", "date"])
    T = T[(T["date"] >= "2019-04-01") & T["f3m"].notna()]
    T["r"] = T.groupby("date")["score"].rank(ascending=False)
    T["um"] = T.groupby("date")["f3m"].transform("mean")
    m = ((T["r"] <= top) & T["dip"]) if kind == "final" else pd.Series(True, index=T.index)
    return T[m].sort_values(["date", "r"]).groupby("date").head(n)


def evaluate(name: str, kind: str = "final") -> tuple[dict, pd.Series]:
    p = picks(name, kind)
    g = p.groupby("date")
    ex = g["f3m"].mean() - COST - g["um"].first()
    yr = ex.groupby(ex.index.year).mean() * 100
    res = {"3か月%": ex.mean() * 100, "t": _t(ex), "上がった割合%": (p["f3m"] > 0).mean() * 100,
           "途中で-30%以下%": (p["mn3m"] <= -0.3).mean() * 100, **{str(y): yr.get(y, np.nan) for y in YEARS}}
    return res, ex


def compare(name: str, ref: str = REF, kind: str = "final") -> dict:
    _, a = evaluate(name, kind)
    _, b = evaluate(ref, kind)
    d = (a - b).dropna()
    yd = d.groupby(d.index.year).mean()
    return {"REFとの差%": d.mean() * 100, "差のt": _t(d), "上回った年": int((yd > 0).sum()), "年数": len(yd)}


def required_t(k: int) -> float:
    """試した案が多いほど、偶然良く見える案が混ざるので厳しくする(k = leaderboard の案の数)"""
    return 2.0 if k <= 5 else 2.5 if k <= 20 else 3.0


def board() -> pd.DataFrame:
    return pd.read_csv(BOARD, dtype={"name": str}) if BOARD.exists() else pd.DataFrame()


def record(name: str, desc: str, kind: str = "final", note: str = "") -> dict:
    """採点して leaderboard.csv に1行(同じ name・kind は上書き)。ゲート1(過去の検証)を満たすかも書く"""
    res, _ = evaluate(name, kind)
    cmp = compare(name, REF, kind) if name != REF else {"REFとの差%": 0.0, "差のt": np.nan, "上回った年": np.nan, "年数": np.nan}
    B = board()
    k = len(set(B["name"]) | {name}) if len(B) else 1
    need = required_t(k)
    gate = bool(name != REF and cmp["差のt"] >= need and cmp["上回った年"] >= 6)
    row = {"name": name, "kind": kind, "desc": desc, "date": date.today().isoformat(), **{k_: round(v, 2) if isinstance(v, float) else v for k_, v in res.items()},
           **{k_: round(v, 2) if isinstance(v, float) else v for k_, v in cmp.items()}, "必要なt": need, "ゲート1": "通過" if gate else "", "note": note}
    if len(B):
        B = B[~((B["name"] == name) & (B["kind"] == kind))]
    B = pd.concat([B, pd.DataFrame([row])], ignore_index=True).sort_values(["kind", "3か月%"], ascending=[True, False])
    B.to_csv(BOARD, index=False, encoding="utf-8")
    return row


if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    B = board()
    print(B.drop(columns=["desc", "note"], errors="ignore").to_string(index=False) if len(B) else "leaderboard.csv はまだ空です")
