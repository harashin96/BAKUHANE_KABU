"""日本株のポートフォリオ型バックテスト(日足、買いのみ)

- シグナルはその日の終値までの情報で計算し、翌営業日の寄り付き(始値)で売買する
- 等金額で N 銘柄を保有し、rebalance 営業日ごとに入れ替える
- コスト: 売買した金額 × cost_bp(片道)。手数料 + スプレッド + 寄り付きの滑りの目安
- 比較の基準: 同じ条件(流動性フィルター)を満たす全銘柄に等金額で投資した場合
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Market:
    adj_close: pd.DataFrame   # 配当・分割調整後の終値(日付 × 銘柄)
    adj_open: pd.DataFrame    # 同じ調整を始値にも適用
    value: pd.DataFrame       # 売買代金(円)
    close: pd.DataFrame       # 分割調整のみの終値(株価水準のフィルター用)

    @staticmethod
    def from_long(df: pd.DataFrame) -> "Market":
        df = df.sort_values(["code", "date"])
        px = df.pivot(index="date", columns="code", values="adj_close")
        cl = df.pivot(index="date", columns="code", values="close")
        op = df.pivot(index="date", columns="code", values="open")
        vol = df.pivot(index="date", columns="code", values="volume")
        factor = px / cl
        return Market(adj_close=px, adj_open=op * factor, value=cl * vol, close=cl)


def clean_split_artifacts(m: Market, up: float = 1.9, down: float = 0.52) -> tuple[Market, pd.DataFrame]:
    """yfinance の株価の「分割が反映されていない段差」や一時的な異常値を直す

    日本株は値幅制限があるため、終値が1日で 1.9倍超 / 0.52倍未満 になることは実際にはほぼ無い。
    そうなった日はデータの段差とみなし、それより前の株価に比率を掛けて、現在の基準につなげる。
    戻り値: (修正後の Market, 段差の一覧[code, date, ratio(株数に掛ける倍率 = 1/価格の比率)])
    """
    c = m.close
    r = c / c.ffill().shift(1)
    art = ((r > up) | (r < down)).fillna(False)
    fac = pd.DataFrame(1.0, index=c.index, columns=c.columns)
    events = []
    for code in art.columns[art.any()]:
        days = art.index[art[code]]
        f = np.ones(len(c.index))
        for d in days:
            k = c.index.get_loc(d)
            f[:k] *= r.at[d, code]
            events.append({"code": code, "date": d, "ratio": 1.0 / r.at[d, code]})
        fac[code] = f
    cm = Market(adj_close=m.adj_close * fac, adj_open=m.adj_open * fac, value=m.value, close=m.close * fac)
    return cm, pd.DataFrame(events, columns=["code", "date", "ratio"])


def eligible(m: Market, min_value_oku: float = 1.0, min_price: float = 200, min_history: int = 260) -> pd.DataFrame:
    """その日に売買対象にしてよい銘柄(過去20日の売買代金の中央値・株価・上場からの日数)"""
    med_val = m.value.rolling(20, min_periods=15).median()
    hist = m.adj_close.notna().cumsum()
    return (med_val >= min_value_oku * 1e8) & (m.close >= min_price) & (hist >= min_history)


def run_portfolio(m: Market, score: pd.DataFrame, elig: pd.DataFrame, n: int = 30, rebalance: int = 5,
                  cost_bp: float = 15.0, ascending: bool = False) -> pd.DataFrame:
    """score が高い(ascending=True なら低い)上位 n 銘柄を保有。戻り値: 日次の損益(コスト前後)"""
    dates = score.index
    oo = m.adj_open.shift(-1) / m.adj_open - 1  # 日 t の寄り付き → 翌日の寄り付き
    oo = oo.clip(-0.5, 1.0)
    s = score.where(elig)
    w_prev = pd.Series(0.0, index=score.columns)
    gross, cost, nhold = [], [], []
    w = w_prev
    for i in range(len(dates) - 1):
        t = dates[i]
        if i % rebalance == 0:
            row = s.loc[t].dropna()
            if len(row) >= n:
                pick = row.nsmallest(n).index if ascending else row.nlargest(n).index
                w = pd.Series(0.0, index=score.columns)
                w[pick] = 1.0 / n
            else:
                w = pd.Series(0.0, index=score.columns)
        # 日 t の終値で決めた w を、日 t+1 の寄り付きから保有
        r = oo.iloc[i + 1].fillna(0.0)
        turn = (w - w_prev).abs().sum()
        gross.append(float((w * r).sum()))
        cost.append(turn * cost_bp / 1e4)
        nhold.append(int((w > 0).sum()))
        # 値動きでウェイトがずれる分(次の入れ替えまでの間)
        grown = w * (1 + r)
        w_prev = grown / grown.sum() if grown.sum() > 0 else grown
        w = w_prev
    idx = dates[1:len(dates)]
    out = pd.DataFrame({"gross": gross, "cost": cost, "n": nhold}, index=idx)
    out["net"] = out["gross"] - out["cost"]
    return out


def benchmark(m: Market, elig: pd.DataFrame) -> pd.Series:
    """流動性フィルターを満たす全銘柄の等金額平均(run_portfolio と同じ日付の付け方)"""
    oo = (m.adj_open.shift(-1) / m.adj_open - 1).clip(-0.5, 1.0)
    e = elig.shift(1, fill_value=False).astype(bool)  # 前日の終値で判定 → その日の寄り付きから保有
    return oo.where(e).mean(axis=1).iloc[1:]


def perf(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {"年率%": np.nan, "ボラ%": np.nan, "シャープ": np.nan, "最大DD%": np.nan}
    eq = (1 + r).cumprod()
    return {"年率%": float((eq.iloc[-1] ** (252 / len(r)) - 1) * 100), "ボラ%": float(r.std() * np.sqrt(252) * 100),
            "シャープ": float(r.mean() / r.std() * np.sqrt(252)),
            "最大DD%": float(((eq.cummax() - eq) / eq.cummax()).max() * 100)}
