"""爆ハネ(3か月以内に+30%)と暴落(3か月以内に-30%)の確率モデル

研究で確かめたこと(2019〜2025年、毎回の上位20銘柄、取っておいた直近1年でも同じ傾向):
- 「爆ハネ確率 − 暴落確率」の上位は、3か月リターンが全銘柄平均より +2.8%(年換算 +11%)高い。t=1.85
- 爆ハネ確率だけで並べると、値動きの荒い株ばかりになり暴落も多い(平均リターンは伸びない)
- 買い時: 押し目・ブレイク・出来高急増などを待っても、ランキング入りの翌日に買うのを上回らなかった
- 売り時: 3か月持つのが平均で最良。-20%損切りは平均を少し下げるが最悪ケースを小さくする
"""
from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Market, clean_split_artifacts, eligible
from .config import DATA, ROOT
from .fundamentals import daily_panels, doc_features, load_splits, load_tidy

log = logging.getLogger("jpstocks")
MODEL = ROOT / "models" / "jump_model.pkl"
H = 63            # 3か月(営業日)
JUMP, CRASH = 0.30, -0.30
FIN_SECTORS = ["銀行業", "証券、商品先物取引業", "保険業", "その他金融業"]


@dataclass
class World:
    m: Market                 # 修正済みの株価
    P: dict                   # 財務の日次パネル
    feat: dict                # 特徴量(日付×銘柄)
    elig: pd.DataFrame        # 対象銘柄(日付×銘柄)
    universe: pd.DataFrame


def build_world(prices: pd.DataFrame, universe: pd.DataFrame, since: str | None = None,
                min_value_oku: float = 0.3) -> World:
    """株価(長い形式) + EDINET財務 → 特徴量。since を指定すると計算をその日以降に限る(毎日のレポート用)"""
    m0 = Market.from_long(prices)
    m, ev = clean_split_artifacts(m0)
    sp = load_splits()
    if sp is not None and len(ev):
        dup = [((sp.code == c) & ((sp.date - d).abs() <= pd.Timedelta(days=7))).any() for c, d in zip(ev.code, ev.date)]
        sp = pd.concat([sp, ev[~np.array(dup, dtype=bool)]], ignore_index=True)
    elif len(ev):
        sp = ev
    f = doc_features(load_tidy(), sp)
    dates = m.close.index
    calc = dates
    if since:
        pos = dates.searchsorted(pd.Timestamp(since))
        calc = dates[max(0, pos - 320):]   # 財務の数字は最大300営業日前の書類まで引き継ぐので、少し前から計算
        dates = dates[pos:]
    cols = m.close.columns
    P = {k: v.loc[dates] for k, v in daily_panels(f, calc, cols).items()}
    P["mcap"] = m.close.reindex(dates) * P["shares_cur"]
    fin = set(universe.loc[universe["sector33"].isin(FIN_SECTORS), "code"].astype(str))
    el = eligible(m, min_value_oku).reindex(dates).fillna(False)
    el = el & np.array([c not in fin for c in cols]) & P["mcap"].notna() & P["equity"].gt(0)
    feat = make_features(m, P, dates)
    return World(m=m, P=P, feat=feat, elig=el, universe=universe)


def make_features(m: Market, P: dict, dates) -> dict:
    cols = m.close.columns
    px = m.adj_close.reindex(dates)
    mc, ta, ni = P["mcap"], P["total_assets"], P["net_income"]
    # 移動計算は少し前の期間も使う
    full_px = m.adj_close
    r1f = full_px.pct_change(fill_method=None)
    valf = m.value
    def rd(x):
        return x.reindex(dates)
    idx = np.arange(len(dates))
    chg = (ni != ni.shift(1)) & ni.notna()
    last = pd.DataFrame(np.where(chg, idx[:, None], np.nan), index=dates, columns=cols).ffill()
    up = r1f.clip(lower=0).rolling(14).mean()
    dn = (-r1f.clip(upper=0)).rolling(14).mean()
    return {
        "NCR": P["net_cash"] / mc, "EY": ni / mc, "BP": P["equity"] / mc, "DY": P["div_total"] / mc,
        "CFOY": P["op_cf"] / mc, "OIY": P["op_income"] / mc, "ROE": ni / P["equity"],
        "OPM": P["op_income"] / P["sales"], "NIg": P["net_income_g"], "OIg": P["op_income_g"], "SALESg": P["sales_g"],
        "EQR": P["equity"] / ta, "CASHY": P["cash"] / mc, "SIZE": np.log(mc),
        "VOL60": rd(r1f.rolling(60, min_periods=40).std()),
        "MOM12_1": rd(full_px.shift(21) / full_px.shift(252) - 1), "MOM3": rd(full_px / full_px.shift(63) - 1),
        "RET1M": rd(full_px / full_px.shift(21) - 1), "RET5": rd(full_px / full_px.shift(5) - 1),
        "HI52": rd(full_px / full_px.rolling(252, min_periods=200).max()),
        "LO52": rd(full_px / full_px.rolling(252, min_periods=200).min()),
        "TURN": rd(valf.rolling(20, min_periods=15).median()) / mc,
        "VOLSURGE": rd(valf.rolling(5).mean() / valf.rolling(120, min_periods=60).mean()),
        "MAXRET20": rd(r1f.rolling(20).max()),
        "MA25GAP": rd(full_px / full_px.rolling(25).mean() - 1), "MA75GAP": rd(full_px / full_px.rolling(75).mean() - 1),
        "RSI14": rd(up / (up + dn)),
        "AGE": pd.DataFrame(idx[:, None] - last.to_numpy(), index=dates, columns=cols),
        "ACC": (ni - P["op_cf"]) / ta, "PRICE": np.log(m.close.reindex(dates)),
    }


FEATURES = ["NCR", "EY", "BP", "DY", "CFOY", "OIY", "ROE", "OPM", "NIg", "OIg", "SALESg", "EQR", "CASHY", "SIZE",
            "VOL60", "MOM12_1", "MOM3", "RET1M", "RET5", "HI52", "LO52", "TURN", "VOLSURGE", "MAXRET20",
            "MA25GAP", "MA75GAP", "RSI14", "AGE", "ACC", "PRICE"]
RAW = ["VOL60", "SIZE", "MAXRET20"]   # 順位に加えて、生の値も使う項目


def cross_section(w: World, i: int) -> pd.DataFrame:
    """日 i の対象銘柄の特徴量(順位 0〜1 + 一部は生の値)"""
    e = w.elig.iloc[i].to_numpy()
    cols = w.elig.columns[e]
    df = pd.DataFrame({k: w.feat[k].iloc[i].to_numpy()[e] for k in FEATURES}, index=cols)
    X = df.rank(pct=True).add_prefix("r_")
    for k in RAW:
        X[k] = df[k]
    return X, df


def make_samples(w: World, step: int = 5, start: str = "2017-08-01") -> pd.DataFrame:
    px = w.m.adj_close.reindex(w.elig.index)
    ao = w.m.adj_open.reindex(w.elig.index)
    fut_max = px[::-1].rolling(H, min_periods=40).max()[::-1].shift(-1)
    fut_min = px[::-1].rolling(H, min_periods=40).min()[::-1].shift(-1)
    entry = ao.shift(-1)
    jump = (fut_max / entry - 1) >= JUMP
    crash = (fut_min / entry - 1) <= CRASH
    dates = w.elig.index
    out = []
    for i in range(dates.searchsorted(pd.Timestamp(start)), len(dates) - H - 2, step):
        X, _ = cross_section(w, i)
        if len(X) < 100:
            continue
        X["jump"] = jump.iloc[i].reindex(X.index).to_numpy()
        X["crash"] = crash.iloc[i].reindex(X.index).to_numpy()
        X["date"] = dates[i]
        out.append(X)
    return pd.concat(out)


def train(samples: pd.DataFrame) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    cols = [c for c in samples.columns if c.startswith("r_")] + RAW
    models = {}
    for tgt in ["jump", "crash"]:
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                             min_samples_leaf=300, l2_regularization=1.0, random_state=0)
        clf.fit(samples[cols], samples[tgt].astype(int))
        models[tgt] = clf
    return {"models": models, "cols": cols, "trained_until": str(samples["date"].max().date()),
            "n_samples": len(samples), "base_jump": float(samples["jump"].mean()), "base_crash": float(samples["crash"].mean())}


def save_model(bundle: dict):
    MODEL.parent.mkdir(exist_ok=True)
    with open(MODEL, "wb") as f:
        pickle.dump(bundle, f)


def load_model() -> dict:
    if not MODEL.exists():
        raise FileNotFoundError("models/jump_model.pkl がありません。先に scripts/20_train_jump_model.py を実行してください。")
    with open(MODEL, "rb") as f:
        return pickle.load(f)


def score_day(w: World, bundle: dict, i: int = -1) -> pd.DataFrame:
    """日 i(既定: 最新)の全対象銘柄の 爆ハネ確率・暴落確率・スコア"""
    i = i if i >= 0 else len(w.elig.index) + i
    X, raw = cross_section(w, i)
    cols = bundle["cols"]
    out = pd.DataFrame(index=X.index)
    out["p_jump"] = bundle["models"]["jump"].predict_proba(X[cols])[:, 1]
    out["p_crash"] = bundle["models"]["crash"].predict_proba(X[cols])[:, 1]
    out["score"] = out["p_jump"] - out["p_crash"]
    d = w.elig.index[i]
    P = w.P
    out["price"] = w.m.close.loc[d, out.index]
    out["mcap_oku"] = P["mcap"].loc[d, out.index] / 1e8
    out["PER"] = 1 / raw["EY"]
    out["PBR"] = 1 / raw["BP"]
    out["NCR"] = raw["NCR"]
    out["DY"] = raw["DY"] * 100
    out["RET1M"] = raw["RET1M"] * 100
    out["MOM3"] = raw["MOM3"] * 100
    out["HI52"] = raw["HI52"] * 100
    out["VOLSURGE"] = raw["VOLSURGE"]
    out["VOL60"] = raw["VOL60"] * np.sqrt(252) * 100
    out["MA25GAP"] = raw["MA25GAP"] * 100
    out["value_oku"] = w.m.value.reindex(w.elig.index).iloc[max(0, i - 19):i + 1][out.index].median() / 1e8
    out["date"] = d
    return out.sort_values("score", ascending=False)
