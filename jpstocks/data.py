"""データの取得と保存(JPXの銘柄一覧 + yfinance の日足)

注意:
- yfinance は Yahoo Finance の非公式な取得方法。個人の研究・運用の範囲で、間隔を空けて使う
- Yahoo には「現在上場している銘柄」しかない。過去に上場廃止になった銘柄が抜けるため、
  バックテストは実際より良く見えやすい(生存者バイアス)。この点は検証結果の解釈で考慮する
"""
from __future__ import annotations

import io
import logging
import time

import numpy as np
import pandas as pd

from .config import DATA

log = logging.getLogger("jpstocks")

JPX_LIST_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
UNIVERSE = DATA / "universe.csv"
PRICES = DATA / "prices.parquet"
PRICES_CSV = DATA / "prices.csv.gz"   # 共有・分析用の圧縮CSV(parquet を読めない環境向け)
SPLITS = DATA / "splits.csv"


def fetch_universe(markets: list[str], sizes: list[str] | None = None) -> pd.DataFrame:
    """JPXの「東証上場銘柄一覧」から、普通株の銘柄リストを作る"""
    import requests
    r = requests.get(JPX_LIST_URL, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    raw = pd.read_excel(io.BytesIO(r.content), dtype=str)
    cols = {c: c.strip() for c in raw.columns}
    raw = raw.rename(columns=cols)

    def pick(*names):
        for n in names:
            for c in raw.columns:
                if n in c:
                    return c
        raise KeyError(f"列が見つかりません: {names} / 実際の列: {list(raw.columns)}")

    df = pd.DataFrame({
        "code": raw[pick("コード")].str.strip(),
        "name": raw[pick("銘柄名")].str.strip(),
        "market": raw[pick("市場・商品区分", "市場")].str.strip(),
        "sector33": raw[pick("33業種区分")].str.strip(),
        "sector17": raw[pick("17業種区分")].str.strip(),
        "size": raw[pick("規模区分")].str.strip(),
    })
    mask = df["market"].apply(lambda m: any(k in str(m) for k in markets)) & ~df["market"].str.contains("ETF|ETN|REIT|PRO", na=False)
    if sizes:
        mask &= df["size"].isin(sizes)
    df = df[mask].reset_index(drop=True)
    df["ticker"] = df["code"] + ".T"
    DATA.mkdir(exist_ok=True)
    df.to_csv(UNIVERSE, index=False, encoding="utf-8-sig")
    log.info(f"銘柄一覧: {len(df)} 銘柄を保存 → {UNIVERSE}")
    return df


def load_universe() -> pd.DataFrame:
    if not UNIVERSE.exists():
        raise FileNotFoundError("data/universe.csv がありません。scripts/01_fetch_universe.py を先に実行してください。")
    return pd.read_csv(UNIVERSE, dtype={"code": str})


def _yf():
    import yfinance as yf
    # 並列取得時の「database is locked」対策: キャッシュをプロジェクト内に置く
    cache = DATA / "yf_cache"
    cache.mkdir(parents=True, exist_ok=True)
    try:
        yf.set_tz_cache_location(str(cache))
    except Exception:
        pass
    return yf


def _download_chunk(tickers: list[str], start: str, threads: bool = True, splits_out: list | None = None) -> pd.DataFrame:
    yf = _yf()
    raw = yf.download(tickers, start=start, auto_adjust=False, actions=splits_out is not None, group_by="ticker",
                      threads=threads, progress=False)
    rows = []
    for t in tickers:
        try:
            d = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        d = d.dropna(subset=["Close"])
        if d.empty:
            continue
        if splits_out is not None and "Stock Splits" in d.columns:
            sp = d["Stock Splits"].fillna(0)
            for dt, v in sp[sp != 0].items():
                splits_out.append({"code": t.replace(".T", ""), "date": pd.Timestamp(dt).tz_localize(None) if pd.Timestamp(dt).tzinfo else pd.Timestamp(dt), "ratio": float(v)})
        rows.append(pd.DataFrame({
            "date": d.index.tz_localize(None) if d.index.tz is not None else d.index,
            "code": t.replace(".T", ""), "open": d["Open"].to_numpy(), "high": d["High"].to_numpy(),
            "low": d["Low"].to_numpy(), "close": d["Close"].to_numpy(), "adj_close": d["Adj Close"].to_numpy(),
            "volume": d["Volume"].to_numpy(),
        }))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def fetch_prices(tickers: list[str], start: str, chunk: int = 50, sleep_sec: float = 2.0,
                 update: bool = True, write_csv: bool = True) -> pd.DataFrame:
    """日足を取得して data/prices.parquet に保存

    既存データがある場合: 既に十分な履歴がある銘柄は直近分だけ、新しい銘柄・履歴が短い銘柄は start から取得
    直近分の更新で株式分割が見つかった銘柄は、過去の株価も調整し直すため最初から取り直す(splits.csv にも追記)
    """
    found_splits: list = []
    old = None
    jobs = [(tickers, start)]
    if update and PRICES.exists():
        old = pd.read_parquet(PRICES)
        first = old.groupby("code")["date"].min()
        recent_from = (old["date"].max() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        full_start = pd.Timestamp(start) + pd.Timedelta(days=30)
        # 履歴がそろっている銘柄 = start 付近から取れている、または start より後に上場した銘柄(行数が十分ある)
        n_rows = old.groupby("code").size()
        have_full = set(first[(first <= full_start) | (n_rows.reindex(first.index) >= 60)].index)
        upd = [t for t in tickers if t.replace(".T", "") in have_full]
        new = [t for t in tickers if t.replace(".T", "") not in have_full]
        jobs = [(new, start), (upd, recent_from)]
        log.info(f"履歴を最初から取得: {len(new)} 銘柄 / 直近分だけ更新({recent_from}〜): {len(upd)} 銘柄")
    parts, failed = [], []
    for job_tickers, job_start in jobs:
        jf = []
        for i in range(0, len(job_tickers), chunk):
            batch = job_tickers[i:i + chunk]
            part = pd.DataFrame()
            for attempt in range(3):
                try:
                    part = _download_chunk(batch, job_start, splits_out=found_splits if update else None)
                    break
                except Exception as e:  # 通信エラー・制限は待って再試行
                    log.warning(f"取得失敗({attempt + 1}/3): {e}")
                    time.sleep(sleep_sec * 5 * (attempt + 1))
            if part.empty:
                jf += batch
            else:
                parts.append(part)
                got = set(part["code"])
                jf += [t for t in batch if t.replace(".T", "") not in got]
            log.info(f"{min(i + chunk, len(job_tickers))}/{len(job_tickers)} 銘柄({job_start}〜)")
            time.sleep(sleep_sec)
        # 取得できなかった銘柄を1銘柄ずつ(並列なしで)取り直す
        for t in jf:
            try:
                part = _download_chunk([t], job_start, threads=False)
            except Exception:
                part = pd.DataFrame()
            if part.empty:
                failed.append(t)
            else:
                parts.append(part)
            time.sleep(sleep_sec / 2)
    new_df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    resplit = set()
    if update and old is not None and found_splits:
        sp = pd.DataFrame(found_splits)
        recent = sp[sp["date"] >= pd.Timestamp(recent_from)]
        resplit = set(recent["code"])
        if resplit:
            log.info(f"直近に株式分割・併合があった銘柄 {len(resplit)} 件: 過去の株価を取り直します {sorted(resplit)[:20]}")
            again = []
            for i in range(0, len(resplit), chunk):
                b = [c + ".T" for c in sorted(resplit)[i:i + chunk]]
                try:
                    again.append(_download_chunk(b, start))
                except Exception as e:
                    log.warning(f"取り直し失敗: {e}")
                time.sleep(sleep_sec)
            if again:
                new_df = pd.concat([new_df[~new_df["code"].isin(resplit)]] + again, ignore_index=True)
                old = old[~old["code"].isin(resplit)]
        prev = pd.read_csv(SPLITS, dtype={"code": str}, parse_dates=["date"]) if SPLITS.exists() else pd.DataFrame(columns=["code", "date", "ratio"])
        pd.concat([prev, sp], ignore_index=True).drop_duplicates(["code", "date"]).to_csv(SPLITS, index=False)
    df = pd.concat([old, new_df], ignore_index=True) if old is not None else new_df
    df = df.drop_duplicates(["code", "date"], keep="last").sort_values(["code", "date"]).reset_index(drop=True)
    df["volume"] = df["volume"].astype(np.float64)
    df.to_parquet(PRICES, index=False)
    if write_csv:
        df.to_csv(PRICES_CSV, index=False, compression="gzip")
    n_years = df.groupby("code")["date"].min()
    log.info(f"保存: {PRICES}  {df['code'].nunique()} 銘柄 / {len(df):,} 行 / {df['date'].min().date()} 〜 {df['date'].max().date()}"
             f"  (2011年以前から履歴がある銘柄: {(n_years < pd.Timestamp('2011-01-01')).sum()})")
    if failed:
        log.warning(f"取得できなかった銘柄: {len(failed)}(上場が新しい・データなし等) → data/failed_tickers.csv")
        pd.Series(failed).to_csv(DATA / "failed_tickers.csv", index=False)
    return df


def load_prices() -> pd.DataFrame:
    if not PRICES.exists() and PRICES_CSV.exists():
        return pd.read_csv(PRICES_CSV, parse_dates=["date"], dtype={"code": str})
    if not PRICES.exists():
        raise FileNotFoundError("data/prices.parquet がありません。scripts/02_fetch_prices.py を先に実行してください。")
    return pd.read_parquet(PRICES)



def fetch_splits(tickers: list[str], start: str = "2015-01-01", chunk: int = 50, sleep_sec: float = 2.0) -> pd.DataFrame:
    """株式分割・併合の履歴(yfinance の Stock Splits)を data/splits.csv に保存

    yfinance の株価は分割をさかのぼって調整済みのため、財務データの株数を同じ基準にそろえるのに使う
    """
    yf = _yf()
    rows, failed = [], []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        for attempt in range(3):
            try:
                raw = yf.download(batch, start=start, actions=True, auto_adjust=False, group_by="ticker",
                                  threads=True, progress=False)
                break
            except Exception as e:
                log.warning(f"取得失敗({attempt + 1}/3): {e}")
                time.sleep(sleep_sec * 5 * (attempt + 1))
        else:
            failed += batch
            continue
        for t in batch:
            try:
                d = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                s = d["Stock Splits"]
            except KeyError:
                failed.append(t)
                continue
            s = s[s.fillna(0) != 0]
            for dt, v in s.items():
                rows.append({"code": t.replace(".T", ""), "date": pd.Timestamp(dt).tz_localize(None) if pd.Timestamp(dt).tzinfo else pd.Timestamp(dt), "ratio": float(v)})
        log.info(f"{min(i + chunk, len(tickers))}/{len(tickers)} 銘柄")
        time.sleep(sleep_sec)
    df = pd.DataFrame(rows, columns=["code", "date", "ratio"]).drop_duplicates()
    df.to_csv(SPLITS, index=False)
    log.info(f"分割・併合: {len(df)} 件 / {df['code'].nunique()} 銘柄 → {SPLITS}  (取得できなかった銘柄 {len(failed)})")
    return df
