"""EDINETの財務データ(fund_tidy.csv)を、日々の「その日までに公表済みの数字」に変換する

- 書類の提出日(submit_date)以降の取引日にだけ数字を使う(発表前の数字は使わない)
- 株式分割: yfinance の株価は分割をさかのぼって調整済みなので、株数も「現在の基準」にそろえる
  (前後の書類で株数が 1.45倍超 / 0.7倍未満 に変わったら分割・併合とみなす)
- 金額は合計値(純利益・純資産など)を使い、1株あたりの数字(EPS等)は分割の影響を受けるので使わない
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import DATA

TIDY = DATA / "edinet" / "fund_tidy.csv"
ANNUAL = {"120", "130"}


def load_tidy(path=TIDY) -> pd.DataFrame:
    f = pd.read_csv(path, dtype={"code": str, "docTypeCode": str, "docID": str})
    # 日付の書き方が混ざっていても読めるように(例: 2026-10-19 / 2026-10-19 00:00:00)
    f["submit_date"] = pd.to_datetime(f["submit_date"].astype(str).str[:10], errors="coerce")
    f["periodEnd"] = pd.to_datetime(f["periodEnd"].astype(str).str[:10], errors="coerce")
    f = f.dropna(subset=["submit_date"])
    f["code"] = f["code"].astype(str).str[:4]
    return f.sort_values(["code", "submit_date"]).reset_index(drop=True)


def _split_adjusted_shares(f: pd.DataFrame, splits: pd.DataFrame | None = None) -> pd.Series:
    """各書類の発行済株式数(自己株式を除く)を、現在の株数の基準に換算

    - 書類と書類の間の分割: 前後の書類の株数が 1.45倍超 / 0.7倍未満 に変わったら分割・併合とみなす
      (EDINETの株数どうしで比べるので、分割日のずれやデータ提供元の抜けに左右されない)
    - 最新の書類より後の分割: splits(yfinanceの分割履歴 + 株価の段差)から掛ける
    """
    total = f["shares_filing"].fillna(f["shares"])
    out = total - f["treasury"].fillna(0)
    out = out.where(out > 0, total)
    adj = pd.Series(np.nan, index=f.index)
    sp = {c: g for c, g in splits.groupby("code")} if splits is not None else {}
    for code, g in f.assign(total=total, out=out).groupby("code"):
        g = g.dropna(subset=["total"])
        if g.empty:
            continue
        t = g["total"].to_numpy()
        ratio = np.ones(len(t))
        ratio[1:] = t[1:] / t[:-1]
        split = np.where((ratio > 1.45) | (ratio < 0.7), ratio, 1.0)
        later = np.cumprod(split[::-1])[::-1]
        later = np.append(later[1:], 1.0)
        tail = 1.0
        if code in sp:
            last = g["submit_date"].max()
            s2 = sp[code]
            tail = float(s2.loc[s2["date"] > last, "ratio"].prod())
        adj[g.index] = g["out"].to_numpy() * later * tail
    return adj


def load_splits(path=None) -> pd.DataFrame | None:
    p = path or (DATA / "splits.csv")
    try:
        s = pd.read_csv(p, dtype={"code": str}, parse_dates=["date"])
    except FileNotFoundError:
        return None
    return s[s["ratio"].between(0.02, 50)]  # まれにある異常値(例: 0.0000003)を除く


def doc_features(f: pd.DataFrame, splits: pd.DataFrame | None = None) -> pd.DataFrame:
    """書類ごとの派生項目(現在基準の株数、配当総額、前年比の伸び)"""
    f = f.copy()
    f["shares_cur"] = _split_adjusted_shares(f, splits)
    shares_doc = (f["shares_filing"].fillna(f["shares"]) - f["treasury"].fillna(0))
    f["div_total"] = f["dps"] * shares_doc
    f["inv_securities"] = f["inv_securities"].fillna(0)
    f["net_cash"] = f["current_assets"] + 0.7 * f["inv_securities"] - f["liabilities"]  # 清原式
    a = f[f["docTypeCode"].isin(ANNUAL)].copy()
    a = a.sort_values(["code", "submit_date"]).drop_duplicates(["code", "periodEnd"], keep="last")
    for col in ["net_income", "op_income", "sales"]:
        prev = a.groupby("code")[col].shift(1)
        gap = a.groupby("code")["submit_date"].diff().dt.days
        g = (a[col] - prev) / prev.abs()
        a[col + "_g"] = g.where(gap.between(250, 500)).clip(-3, 3)
    f = f.merge(a[["docID", "net_income_g", "op_income_g", "sales_g"]], on="docID", how="left")
    return f


def _to_daily(docs: pd.DataFrame, col: str, dates: pd.DatetimeIndex, codes, max_age: int) -> pd.DataFrame:
    d = docs.dropna(subset=[col])
    pos = dates.searchsorted(d["submit_date"].to_numpy())  # 提出日当日(取引日なら)から使える
    ok = pos < len(dates)
    d = d[ok].assign(avail=dates[pos[ok]])
    p = d.drop_duplicates(["avail", "code"], keep="last").pivot(index="avail", columns="code", values=col)
    p = p.reindex(index=dates, columns=codes)
    return p.ffill(limit=max_age)


def daily_panels(f: pd.DataFrame, dates: pd.DatetimeIndex, codes) -> dict[str, pd.DataFrame]:
    """日付 × 銘柄の表。年次の項目は有価証券報告書から、貸借対照表と株数は最新の書類(半期含む)から"""
    ann = f[f["docTypeCode"].isin(ANNUAL)]
    out = {}
    for col in ["net_income", "op_income", "sales", "op_cf", "div_total", "net_income_g", "op_income_g", "sales_g"]:
        out[col] = _to_daily(ann, col, dates, codes, max_age=300)
    for col in ["equity", "net_cash", "cash", "liabilities", "total_assets", "current_assets", "shares_cur"]:
        out[col] = _to_daily(f, col, dates, codes, max_age=300)
    return out
