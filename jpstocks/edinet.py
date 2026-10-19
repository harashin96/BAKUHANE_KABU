"""EDINET(金融庁の電子開示システム)API v2 から、財務データを「提出日つき」で取得する

1. 書類一覧(日付ごと)… 有価証券報告書などの提出日・書類ID・証券コードを集める → data/edinet/index.csv
2. 書類本体 … 各書類から「主要な経営指標等の推移」(売上・利益・純資産・EPS・BPS・ROE など)を取り出す
               → data/edinet/fundamentals.csv(1行 = 書類 × 項目)

提出日(submit_date)より後の株価にだけ使えば、発表前の数字を使ってしまう問題を避けられる。
APIキー: 環境変数 EDINET_API_KEY、または config/edinet_key.txt に1行で記入
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
import zipfile
from datetime import date, timedelta

import pandas as pd

from .config import DATA, ROOT

log = logging.getLogger("jpstocks")
BASE = "https://api.edinet-fsa.go.jp/api/v2"
EDIR = DATA / "edinet"
INDEX = EDIR / "index.csv"
INDEX_DONE = EDIR / "index_done.txt"
FUND = EDIR / "fundamentals.csv"
FUND_DONE = EDIR / "fundamentals_done.txt"

# 集める書類の種類: 120 有価証券報告書 / 130 訂正有価証券報告書 / 140 四半期報告書(2024年3月まで) / 160 半期報告書
DOC_TYPES = {"120", "130", "140", "160"}
INDEX_COLS = ["docID", "secCode", "edinetCode", "filerName", "docTypeCode", "periodStart", "periodEnd",
              "submitDateTime", "csvFlag", "xbrlFlag", "withdrawalStatus", "docDescription"]


def api_key() -> str:
    k = os.environ.get("EDINET_API_KEY")
    if not k:
        p = ROOT / "config" / "edinet_key.txt"
        if p.exists():
            k = p.read_text(encoding="utf-8").strip()
    if not k:
        raise RuntimeError("EDINETのAPIキーがありません。config/edinet_key.txt に1行で書くか、環境変数 EDINET_API_KEY を設定してください。")
    return k


def _get(url: str, params: dict, retries: int = 4, sleep: float = 1.0):
    import requests
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r
            log.warning(f"HTTP {r.status_code}: {url} {r.text[:200]}")
        except Exception as e:
            log.warning(f"通信エラー({i + 1}/{retries}): {e}")
        time.sleep(sleep * (2 ** i))
    return None


# ---------------------------------------------------------------------------
# 1. 書類一覧
# ---------------------------------------------------------------------------
def list_documents(d: date, key: str) -> list[dict]:
    r = _get(f"{BASE}/documents.json", {"date": d.isoformat(), "type": 2, "Subscription-Key": key})
    if r is None:
        raise RuntimeError(f"{d} の書類一覧を取得できません")
    js = r.json()
    if "results" not in js:
        msg = js.get("metadata", {}).get("message") or js.get("message") or str(js)[:200]
        raise RuntimeError(f"{d}: {msg}")
    return js["results"]


def build_index(start: date, end: date, key: str, sleep: float = 0.5) -> int:
    """start〜end の各日の書類一覧から、対象の書類だけを index.csv に追記(途中から再開できる)"""
    EDIR.mkdir(parents=True, exist_ok=True)
    done = set(INDEX_DONE.read_text().split()) if INDEX_DONE.exists() else set()
    new_file = not INDEX.exists()
    n_add = 0
    with open(INDEX, "a", newline="", encoding="utf-8") as f, open(INDEX_DONE, "a") as fd:
        w = csv.DictWriter(f, fieldnames=INDEX_COLS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        d = start
        today = date.today()
        while d <= end:
            ds = d.isoformat()
            if ds not in done and d.weekday() < 5:  # 提出はほぼ平日のみ
                try:
                    rows = list_documents(d, key)
                except RuntimeError as e:
                    log.warning(str(e))
                    d += timedelta(days=1)
                    time.sleep(sleep)
                    continue
                keep = [r for r in rows if r.get("docTypeCode") in DOC_TYPES and r.get("secCode")]
                for r in keep:
                    w.writerow(r)
                n_add += len(keep)
                if d < today - timedelta(days=2):  # 直近の日は次回もう一度見る
                    fd.write(ds + "\n")
                f.flush()
                fd.flush()
                if d.day <= 3 and d.weekday() == 0 or d.day == 1:
                    log.info(f"{ds} まで完了(累計 {n_add} 件追加)")
                time.sleep(sleep)
            d += timedelta(days=1)
    return n_add


def load_index() -> pd.DataFrame:
    df = pd.read_csv(INDEX, dtype=str).drop_duplicates("docID")
    df["submit_date"] = pd.to_datetime(df["submitDateTime"]).dt.normalize()
    df["code"] = df["secCode"].str[:4]  # EDINETの証券コードは5桁(末尾0)
    return df


# ---------------------------------------------------------------------------
# 2. 書類本体から数値を取り出す
# ---------------------------------------------------------------------------
KEEP_PATTERNS = ("SummaryOfBusinessResults", "NumberOfIssuedShares", "TotalNumberOfIssuedShares")


# 貸借対照表などから個別に取る項目(ネットキャッシュ比率・営業利益など)。要素名の完全一致
KEEP_EXACT = {
    "CurrentAssets", "InvestmentSecurities", "Liabilities", "NetAssets", "CashAndDeposits", "OperatingIncome",
    "CurrentAssetsIFRS", "LiabilitiesIFRS", "OtherFinancialAssetsNCAIFRS", "CashAndCashEquivalentsIFRS",
    "OperatingProfitLossIFRS", "EquityIFRS",
    "TotalNumberOfSharesHeldTreasurySharesEtc",
}


def _ctx_ok(ctx) -> bool:
    """当期・前期・提出日時点だけ残す(2〜4期前の数字はその年の書類から取れるので保存しない)"""
    c = str(ctx)
    return c.startswith(("Current", "Prior1", "Interim", "FilingDate"))


def _keep(element: str) -> bool:
    local = element.split(":")[-1]
    return local in KEEP_EXACT or any(p in local for p in KEEP_PATTERNS)


def parse_csv_zip(content: bytes) -> list[dict]:
    """type=5(XBRLをCSVにしたもの)の zip から、主要な経営指標を取り出す(UTF-16・タブ区切り)"""
    out = []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        for name in z.namelist():
            if not name.endswith(".csv") or "XBRL_TO_CSV" not in name:
                continue
            raw = z.read(name)
            try:
                df = pd.read_csv(io.BytesIO(raw), sep="\t", encoding="utf-16", dtype=str)
            except Exception:
                continue
            if "要素ID" not in df.columns:
                continue
            df = df[df["要素ID"].astype(str).map(_keep)]
            if "コンテキストID" in df.columns:
                df = df[df["コンテキストID"].map(_ctx_ok)]
            for r in df.to_dict("records"):
                out.append({"element": str(r["要素ID"]).split(":")[-1], "context": r.get("コンテキストID", ""),
                            "value": r.get("値"), "unit": r.get("単位", "")})
    return out


def parse_xbrl_zip(content: bytes) -> list[dict]:
    """type=1(XBRL本体)の zip から、主要な経営指標を取り出す(CSVが無い古い書類用)"""
    import xml.etree.ElementTree as ET
    out = []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        for name in z.namelist():
            if not (name.endswith(".xbrl") and "PublicDoc" in name):
                continue
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            for el in root.iter():
                if not isinstance(el.tag, str):
                    continue
                local = el.tag.split("}")[-1]
                if not _keep(local):
                    continue
                ctx = el.get("contextRef", "")
                if not _ctx_ok(ctx):
                    continue
                txt = (el.text or "").strip()
                if txt:
                    out.append({"element": local, "context": ctx, "value": txt, "unit": el.get("unitRef", "")})
    return out


class FetchError(Exception):
    """通信できなかった(制限・障害)。この書類は「取得済み」にしない"""


def fetch_document(doc: dict, key: str) -> list[dict]:
    use_csv = str(doc.get("csvFlag", "0")) == "1"
    r = _get(f"{BASE}/documents/{doc['docID']}", {"type": 5 if use_csv else 1, "Subscription-Key": key})
    if r is None:
        raise FetchError(doc["docID"])
    if r.content[:2] != b"PK":  # zipでない = 書類が無い/非公開(エラーのJSON)。取り直しても同じなので取得済み扱い
        return []
    rows = parse_csv_zip(r.content) if use_csv else parse_xbrl_zip(r.content)
    if not rows and use_csv:  # CSVで取れなければXBRLで再挑戦
        r2 = _get(f"{BASE}/documents/{doc['docID']}", {"type": 1, "Subscription-Key": key})
        if r2 is None:
            raise FetchError(doc["docID"])
        if r2.content[:2] == b"PK":
            rows = parse_xbrl_zip(r2.content)
    return rows


def build_fundamentals(index: pd.DataFrame, key: str, sleep: float = 1.0, limit: int | None = None,
                       collect: list | None = None) -> int:
    """index の各書類を取得して fundamentals.csv に追記(途中から再開できる)

    collect にリストを渡すと、今回取得した行もそこに入れる(毎日の差分更新用)"""
    EDIR.mkdir(parents=True, exist_ok=True)
    done = set(FUND_DONE.read_text().split()) if FUND_DONE.exists() else set()
    todo = index[~index["docID"].isin(done)]
    if limit:
        todo = todo.head(limit)
    log.info(f"取得する書類: {len(todo)} 件(取得済み {len(done)} 件)")
    new_file = not FUND.exists()
    cols = ["docID", "code", "docTypeCode", "submit_date", "periodEnd", "element", "context", "value", "unit"]
    n = 0
    t0 = time.time()
    with open(FUND, "a", newline="", encoding="utf-8") as f, open(FUND_DONE, "a") as fd:
        w = csv.DictWriter(f, fieldnames=cols)
        if new_file:
            w.writeheader()
        fails = 0
        for i, doc in enumerate(todo.to_dict("records")):
            try:
                rows = fetch_document(doc, key)
                fails = 0
            except FetchError:
                fails += 1
                log.warning(f"{doc['docID']}: 通信できず(連続 {fails} 回)。あとで取り直します")
                if fails >= 10:
                    log.error("通信できない状態が続くので止めます(アクセス制限・EDINET側の障害の可能性)。"
                              "しばらく(30分〜数時間)空けて同じコマンドを実行すれば続きから再開します。")
                    break
                time.sleep(30 * fails)
                continue
            except Exception as e:  # 書類の中身が壊れている等。取り直しても同じなので取得済み扱い
                log.warning(f"{doc['docID']}: {e}")
                rows = []
            for r in rows:
                row = {"docID": doc["docID"], "code": doc["code"], "docTypeCode": doc["docTypeCode"],
                       "submit_date": str(doc["submit_date"])[:10], "periodEnd": doc.get("periodEnd"), **r}
                w.writerow(row)
                if collect is not None:
                    collect.append(row)
            fd.write(doc["docID"] + "\n")
            n += 1
            if n % 100 == 0:
                f.flush()
                fd.flush()
                el = time.time() - t0
                log.info(f"{n}/{len(todo)} 件  残り約 {el / n * (len(todo) - n) / 60:.0f} 分")
            time.sleep(sleep)
    return n


def save_json(obj, path):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. 研究用の表に整える(1行 = 書類 × 指標、当期の値だけ)
# ---------------------------------------------------------------------------
# 指標名 → 要素名に含まれるキーワード(日本基準 / IFRS / 米国基準 の順に探す)
METRICS = {
    "sales": ["NetSalesSummaryOfBusinessResults", "RevenueIFRSSummaryOfBusinessResults", "OperatingRevenue1SummaryOfBusinessResults",
              "RevenuesUSGAAPSummaryOfBusinessResults", "NetSalesIFRSSummaryOfBusinessResults", "OrdinaryIncomeSummaryOfBusinessResults_Bank"],
    "ordinary_income": ["OrdinaryIncomeLossSummaryOfBusinessResults", "ProfitLossBeforeTaxIFRSSummaryOfBusinessResults",
                        "IncomeBeforeIncomeTaxesUSGAAPSummaryOfBusinessResults"],
    "net_income": ["ProfitLossAttributableToOwnersOfParentSummaryOfBusinessResults", "NetIncomeLossSummaryOfBusinessResults",
                   "ProfitLossAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
                   "NetIncomeLossAttributableToOwnersOfParentUSGAAPSummaryOfBusinessResults"],
    "equity": ["NetAssetsSummaryOfBusinessResults", "EquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
               "EquityAttributableToOwnersOfParentUSGAAPSummaryOfBusinessResults"],
    "total_assets": ["TotalAssetsSummaryOfBusinessResults", "TotalAssetsIFRSSummaryOfBusinessResults",
                     "TotalAssetsUSGAAPSummaryOfBusinessResults"],
    "eps": ["BasicEarningsLossPerShareSummaryOfBusinessResults", "BasicEarningsLossPerShareIFRSSummaryOfBusinessResults",
            "BasicEarningsLossPerShareUSGAAPSummaryOfBusinessResults"],
    "bps": ["NetAssetsPerShareSummaryOfBusinessResults", 
            "EquityAttributableToOwnersOfParentPerShareIFRSSummaryOfBusinessResults",
            "ShareholdersEquityPerShareUSGAAPSummaryOfBusinessResults"],
    "dps": ["DividendPaidPerShareSummaryOfBusinessResults"],
    "roe": ["RateOfReturnOnEquitySummaryOfBusinessResults", "RateOfReturnOnEquityAttributableToOwnersOfParentIFRSSummaryOfBusinessResults",
            "RateOfReturnOnEquityUSGAAPSummaryOfBusinessResults"],
    "op_cf": ["NetCashProvidedByUsedInOperatingActivitiesSummaryOfBusinessResults",
              "CashFlowsFromUsedInOperatingActivitiesIFRSSummaryOfBusinessResults",
              "CashFlowsFromUsedInOperatingActivitiesUSGAAPSummaryOfBusinessResults"],
    "shares": ["TotalNumberOfIssuedSharesSummaryOfBusinessResults"],
    # 貸借対照表(ネットキャッシュ比率 = (流動資産 + 投資有価証券×70% − 負債) ÷ 時価総額)
    "current_assets": ["CurrentAssets", "CurrentAssetsIFRS"],
    "inv_securities": ["InvestmentSecurities", "OtherFinancialAssetsNCAIFRS"],
    "liabilities": ["Liabilities", "LiabilitiesIFRS"],
    "cash": ["CashAndDeposits", "CashAndCashEquivalentsIFRS"],
    "op_income": ["OperatingIncome", "OperatingProfitLossIFRS"],
    "shares_filing": ["NumberOfIssuedSharesAsOfFilingDateIssuedSharesTotalNumberOfSharesEtc"],
    "treasury": ["TotalNumberOfSharesHeldTreasurySharesEtc"],
}
# 当期のコンテキスト: 年次は CurrentYear、半期・四半期は CurrentYTD / InterimPeriod / CurrentQuarter
CUR_CTX = ("CurrentYearDuration", "CurrentYearInstant", "CurrentYTDDuration", "InterimDuration", "InterimInstant",
           "CurrentQuarterInstant", "CurrentYTDInstant", "FilingDateInstant")


def tidy_fundamentals(raw: pd.DataFrame) -> pd.DataFrame:
    """fundamentals.csv(生データ)→ 書類ごとに当期の主要指標を1行にまとめる。連結を優先し、無ければ単体"""
    df = raw.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    ctx = df["context"].astype(str)
    df["cur"] = ctx.map(lambda c: c.split("_")[0] in CUR_CTX)
    df["nonconsol"] = ctx.str.contains("NonConsolidated")
    df = df[df["cur"] & ~ctx.str.contains("Member") | df["cur"] & df["nonconsol"] & (ctx.str.count("Member") == 1)]
    out = []
    for m, keys in METRICS.items():
        for pri, k in enumerate(keys):
            hit = df[df["element"] == k].assign(metric=m, pri=pri)
            out.append(hit)
    if not out:
        return pd.DataFrame()
    a = pd.concat(out)
    a = a.sort_values(["docID", "metric", "nonconsol", "pri"]).drop_duplicates(["docID", "metric"])
    wide = a.pivot(index="docID", columns="metric", values="value")
    meta = raw.drop_duplicates("docID").set_index("docID")[["code", "docTypeCode", "submit_date", "periodEnd"]]
    wide = meta.join(wide, how="inner").reset_index()
    wide["code"] = wide["code"].astype(str).str[:4]
    wide["submit_date"] = pd.to_datetime(wide["submit_date"])
    wide["periodEnd"] = pd.to_datetime(wide["periodEnd"], errors="coerce")
    return wide
