"""J-Quants API(日本取引所グループ公式、v2)から、株価・決算短信の数字・銘柄一覧を日付ごとに取得して手元に保存する

- 株価(日足、上場廃止した銘柄も含む)   /v2/equities/bars/daily?date=   → JQ/bars/YYYY-MM-DD.parquet
- 決算短信の数字(四半期の実績・会社予想)  /v2/fins/summary?date=        → JQ/fins/YYYY-MM-DD.parquet(開示日ごと)
- 銘柄一覧(その日時点)                   /v2/equities/master?date=     → JQ/master/YYYY-MM-DD.parquet(月初)
どれも実データで項目名を確認済み(2026-11-05)。保存先はリポジトリの外(データが大きく、利用規約上も公開しない)。
APIキー: 環境変数 JQUANTS_API_KEY、または C:\\Projects\\JP_STOCKS\\config\\jquants_key.txt(リポジトリの外)
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta

import pandas as pd

from .config import ROOT

log = logging.getLogger("jpstocks")
BASE = "https://api.jquants.com"
JQ = ROOT.parent / "data" / "jquants"
KEY_FILES = [ROOT.parent / "config" / "jquants_key.txt", ROOT / "config" / "jquants_key.txt"]


def api_key() -> str:
    k = os.environ.get("JQUANTS_API_KEY")
    for p in KEY_FILES:
        if not k and p.exists():
            k = p.read_text(encoding="utf-8").strip()
    if not k:
        raise RuntimeError("J-Quants の APIキーがありません(環境変数 JQUANTS_API_KEY か config/jquants_key.txt)")
    return k


def get_all(path: str, params: dict, key: str, retries: int = 5) -> list[dict]:
    """ページ分割(pagination_key)をたどって全件を取る"""
    import requests
    out, p = [], dict(params)
    while True:
        for i in range(retries):
            try:
                r = requests.get(BASE + path, headers={"x-api-key": key}, params=p, timeout=120)
            except Exception as e:
                log.warning(f"通信エラー({i + 1}/{retries}): {e}")
                time.sleep(5 * (i + 1))
                continue
            if r.status_code == 200:
                break
            if r.status_code == 429 or r.status_code >= 500:     # 回数制限・障害は待って再試行
                log.warning(f"HTTP {r.status_code}: {path} {p} 待って再試行")
                time.sleep(20 * (i + 1))
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {path} {p} {r.text[:200]}")
        else:
            raise RuntimeError(f"取得できません: {path} {p}")
        js = r.json()
        out += js.get("data", [])
        if not js.get("pagination_key"):
            return out
        p["pagination_key"] = js["pagination_key"]


def _days(start: date, end: date, weekdays_only: bool = True):
    d = start
    while d <= end:
        if not weekdays_only or d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def fetch_by_date(kind: str, start: date, end: date, key: str, sleep: float = 0.3) -> int:
    """kind = bars / fins / master。日ごとのファイルが無い日だけ取得(途中から再開できる)。直近3日は取り直す"""
    path = {"bars": "/v2/equities/bars/daily", "fins": "/v2/fins/summary", "master": "/v2/equities/master"}[kind]
    out = JQ / kind
    out.mkdir(parents=True, exist_ok=True)
    days = list(_days(start, end))
    if kind == "master":   # 銘柄一覧は月初の営業日だけ
        days = [d for d in days if d == min(x for x in days if (x.year, x.month) == (d.year, d.month))]
    recent = date.today() - timedelta(days=3)
    n, t0 = 0, time.time()
    for k, d in enumerate(days):
        f = out / f"{d.isoformat()}.parquet"
        if f.exists() and d < recent:
            continue
        rows = get_all(path, {"date": d.isoformat()}, key)
        if rows or kind == "fins":
            pd.DataFrame(rows).astype(str).to_parquet(f, index=False)   # 休場日は bars が0件(保存しない)、fins は0件でも保存
        n += 1
        if n % 100 == 0:
            el = time.time() - t0
            log.info(f"J-Quants {kind}: {d} まで({k + 1}/{len(days)} 日)残り約 {el / n * (len(days) - k - 1) / 60:.0f} 分")
        time.sleep(sleep)
    return n


def load(kind: str, cols: list[str] | None = None) -> pd.DataFrame:
    files = sorted((JQ / kind).glob("*.parquet"))
    return pd.concat([pd.read_parquet(f, columns=cols) for f in files], ignore_index=True) if files else pd.DataFrame()
