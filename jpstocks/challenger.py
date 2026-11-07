"""チャレンジャー: 本番(チャンピオン)と並走させる候補のモデル。サイトの表示は変えず、選んだ銘柄だけを記録して後で答え合わせする

- 毎日のレポート(scripts/21_daily_report.py)が models/challengers/*.pkl をすべて採点し、
  3か月の最終候補と同じ選び方(期待スコア60位以内 × 巻き添え安 × 上位5)で選んだ銘柄を reports/shadow_picks.csv に追記する。
  チャンピオン(本番のモデル)の上位5も同じファイルに "champion" として記録する
- 学習: scripts/26_train_challenger.py(手元のPCで。J-Quants の決算短信の全期間が必要。週1回の研究タスクが月1回くらい)
- 答え合わせ: scripts/25_shadow_eval.py → research/lab/shadow.md
- 本番に入れる条件と手順: research/lab/README.md(利用者の承認が必要)

ここに新しい種類の特徴量を足すときは、検証台(research/lab/lab.py)と同じ作り方にすること。
"""
from __future__ import annotations

import logging
import pickle

import numpy as np
import pandas as pd

from .config import ROOT
from .jump import RAW, cross_section, make_samples

log = logging.getLogger("jpstocks")
DIR = ROOT / "models" / "challengers"
LEDGER = ROOT / "reports" / "shadow_picks.csv"
HGB = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=300, l2_regularization=1.0)
# 名前: (説明, 決算短信の特徴量を使うか, 乱数の数, 勾配ブースティングの設定)
SPECS = {
    "M1_ens5": ("今の特徴量 + 決算短信の特徴量8個、乱数5通りの平均(検証: 3か月の最終候補 +2.7%、REF +2.3%)", True, 5, {}),
}


def earn_panels(fins: pd.DataFrame, w) -> dict:
    from .kessan import model_panels
    E = model_panels(fins, w.elig.index, w.elig.columns.astype(str))
    for k in E:
        E[k].columns = w.elig.columns
    return E


def _earn_cross(E: dict, i: int, idx) -> pd.DataFrame:
    X = pd.DataFrame({"e_" + k: v.iloc[i].reindex(idx).to_numpy() for k, v in E.items()}, index=idx)
    for c in ["e_rev_up", "e_rev_down"]:
        if c in X:
            X[c] = X[c].fillna(0)
    return X


def train(name: str, w, fins: pd.DataFrame | None) -> dict:
    """手元のPCで学習(scripts/26_train_challenger.py)。サンプルは本番と同じ(make_samples、5営業日おき)"""
    from sklearn.ensemble import HistGradientBoostingRegressor
    desc, use_earn, nseed, prm = SPECS[name]
    S = make_samples(w)
    cols = [c for c in S.columns if c.startswith("r_")] + RAW
    if use_earn:
        E = earn_panels(fins, w)
        pos = {d: i for i, d in enumerate(w.elig.index)}
        parts = [_earn_cross(E, pos[d], g.index) for d, g in S.groupby("date", sort=False)]
        S = pd.concat([S, pd.concat(parts).set_axis(S.index)], axis=1) if parts else S
        cols += ["e_" + k for k in E]
    ok = S.dropna(subset=["exrank"])
    models = [HistGradientBoostingRegressor(**{**HGB, **prm}, random_state=s).fit(ok[cols], ok["exrank"]) for s in range(nseed)]
    return {"name": name, "desc": desc, "models": models, "cols": cols, "use_earn": use_earn,
            "trained_until": str(S["date"].max().date()), "n_samples": len(ok)}


def save(b: dict):
    DIR.mkdir(parents=True, exist_ok=True)
    with open(DIR / f"{b['name']}.pkl", "wb") as f:
        pickle.dump(b, f)


def load_all() -> list[dict]:
    out = []
    for p in sorted(DIR.glob("*.pkl")) if DIR.exists() else []:
        try:
            with open(p, "rb") as f:
                out.append(pickle.load(f))
        except Exception as e:
            log.warning(f"チャレンジャー {p.name} を読み込めません: {e}")
    return out


def score(b: dict, w, i: int, E: dict | None) -> pd.Series:
    X, _ = cross_section(w, i)
    if b["use_earn"]:
        if E is None:
            raise ValueError("決算短信のデータがありません")
        X = pd.concat([X, _earn_cross(E, i, X.index)], axis=1)
    return pd.Series(np.mean([m.predict(X[b["cols"]]) for m in b["models"]], axis=0), index=X.index)


def run_shadow(w, i: int, today: pd.DataFrame, status: dict, fins: pd.DataFrame | None) -> pd.DataFrame:
    """チャンピオンと各チャレンジャーの最終候補(上位5)を記録して返す。失敗してもサイトの更新は止めない"""
    from .jump import focus_candidates
    d = pd.Timestamp(today["date"].iloc[0]).date().isoformat()
    rows = [("champion", c, k + 1, float(today.loc[c, "score"])) for k, c in enumerate(focus_candidates(today, status).head(5).index)]
    bs = load_all()
    E = None
    if any(b["use_earn"] for b in bs) and fins is not None and len(fins):
        try:
            E = earn_panels(fins, w)
        except Exception as e:
            log.warning(f"チャレンジャー用の決算短信の特徴量を作れません: {e}")
    for b in bs:
        try:
            s = score(b, w, i, E).reindex(today.index)
            t = today.assign(score=s).sort_values("score", ascending=False)
            rows += [(b["name"], c, k + 1, float(t.loc[c, "score"])) for k, c in enumerate(focus_candidates(t, status).head(5).index)]
        except Exception as e:
            log.warning(f"チャレンジャー {b['name']} を採点できません: {e}")
    new = pd.DataFrame(rows, columns=["model", "code", "rank", "score"]).assign(date=d)[["date", "model", "rank", "code", "score"]]
    old = pd.read_csv(LEDGER, dtype={"code": str}) if LEDGER.exists() else pd.DataFrame(columns=new.columns)
    old = old[~((old["date"] == d) & old["model"].isin(new["model"].unique()))]
    allr = pd.concat([old, new], ignore_index=True).astype({"rank": int, "score": float}).sort_values(["date", "model", "rank"])
    allr.to_csv(LEDGER, index=False, float_format="%.4f")
    log.info("並走の記録: " + " / ".join(f"{m}: {' '.join(g['code'])}" for m, g in new.groupby("model")))
    return new
