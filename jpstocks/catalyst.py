"""割安が見直される「きっかけ(カタリスト)」のデータを EDINET から集める

1. 書類一覧(日付ごと)から、次の書類を data/edinet/events.csv に保存する(書類種別コードは実データの書類名で確認済み)
   350 大量保有報告書・変更報告書 / 360 その訂正 / 220 自己株券買付状況報告書 / 230 その訂正
   240 公開買付届出書 / 250 その訂正 / 270 公開買付報告書 / 290 意見表明報告書
   一覧に中身が出るのは、350・360・240・290 は提出から約5年、220 は約1年(古い日は中身が空で返る)
2. アクティビストが出した 350・360 の本体から、保有割合・前回の保有割合・保有目的 → data/edinet/lvh.csv
3. 有価証券報告書(120)の「大株主の状況」→ 上位10株主(data/edinet/holders.csv、手元だけ)と、
   書類ごとの要約(data/edinet/holders_sum.csv、リポジトリに保存)
4. 証券コードと EDINET コードの対応 → data/edinet/edinet_codes.csv(大量保有の「対象の会社」は EDINET コードでしか分からない)

どの数字も、書類の提出日(submit_date)以降の取引日にだけ使う。
"""
from __future__ import annotations

import csv
import io
import logging
import re
import time
import unicodedata
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import ROOT
from .edinet import BASE, EDIR, FetchError, _get, list_documents

log = logging.getLogger("jpstocks")

EVENTS = EDIR / "events.csv"
EVENTS_DONE = EDIR / "events_done.txt"
CODES = EDIR / "edinet_codes.csv"
LVH = EDIR / "lvh.csv"
LVH_DONE = EDIR / "lvh_done.txt"
HOLDERS = EDIR / "holders.csv"
HOLDERS_SUM = EDIR / "holders_sum.csv"
HOLDERS_DONE = EDIR / "holders_done.txt"
ACTIVISTS = ROOT / "config" / "activists.yaml"

EVENT_TYPES = {"220", "230", "240", "250", "270", "290", "350", "360"}
EVENT_COLS = ["docID", "edinetCode", "secCode", "filerName", "docTypeCode", "submitDateTime", "docDescription",
              "issuerEdinetCode", "subjectEdinetCode", "parentDocID", "withdrawalStatus", "csvFlag", "xbrlFlag"]


# ---------------------------------------------------------------------------
# 1. 書類一覧
# ---------------------------------------------------------------------------
def build_events(start: date, end: date, key: str, sleep: float = 0.4) -> int:
    """start〜end の各日の書類一覧から、カタリスト関係の書類を events.csv に追記し、証券コードと EDINET コードの対応も更新する"""
    EDIR.mkdir(parents=True, exist_ok=True)
    done = set(EVENTS_DONE.read_text().split()) if EVENTS_DONE.exists() else set()
    codes = load_codes()
    known = dict(zip(codes["edinetCode"], codes["code"]))
    names = dict(zip(codes["edinetCode"], codes["name"]))
    new_file = not EVENTS.exists()
    n_add = 0
    today = date.today()
    with open(EVENTS, "a", newline="", encoding="utf-8") as f, open(EVENTS_DONE, "a") as fd:
        w = csv.DictWriter(f, fieldnames=EVENT_COLS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        d = start
        while d <= end:
            ds = d.isoformat()
            if ds not in done:
                try:
                    rows = list_documents(d, key)
                except RuntimeError as e:
                    log.warning(str(e))
                    d += timedelta(days=1)
                    time.sleep(sleep)
                    continue
                keep = [r for r in rows if r.get("docTypeCode") in EVENT_TYPES]
                for r in keep:
                    w.writerow(r)
                for r in rows:
                    if r.get("edinetCode") and r.get("secCode"):
                        known[r["edinetCode"]] = str(r["secCode"])[:4]
                        names[r["edinetCode"]] = r.get("filerName")
                n_add += len(keep)
                if d < today - timedelta(days=2):
                    fd.write(ds + "\n")
                f.flush()
                fd.flush()
                if d.day == 1:
                    log.info(f"書類一覧(カタリスト) {ds} まで完了(累計 {n_add} 件追加)")
                time.sleep(sleep)
            d += timedelta(days=1)
    save_codes(known, names)
    return n_add


def load_codes() -> pd.DataFrame:
    if not CODES.exists():
        return pd.DataFrame(columns=["edinetCode", "code", "name"])
    return pd.read_csv(CODES, dtype=str)


def save_codes(known: dict, names: dict) -> None:
    pd.DataFrame({"edinetCode": list(known), "code": list(known.values()), "name": [names.get(k) for k in known]}) \
        .sort_values("edinetCode").to_csv(CODES, index=False)


def load_events() -> pd.DataFrame:
    e = pd.read_csv(EVENTS, dtype=str).drop_duplicates("docID")
    e = e[e["docTypeCode"].isin(EVENT_TYPES) & (e["withdrawalStatus"].fillna("0") == "0")]
    e["submit_date"] = pd.to_datetime(e["submitDateTime"]).dt.normalize()
    c = load_codes().set_index("edinetCode")["code"]
    # 大量保有は issuerEdinetCode、公開買付・意見表明は subjectEdinetCode が対象の会社
    e["target"] = e["issuerEdinetCode"].fillna(e["subjectEdinetCode"]).map(c)
    e.loc[e["docTypeCode"].isin(["220", "230", "290"]), "target"] = e["secCode"].str[:4]   # 自社株買い・意見表明は、提出した会社自身
    return e


# ---------------------------------------------------------------------------
# 2. アクティビストの判定と、大量保有報告書の中身
# ---------------------------------------------------------------------------
def norm_name(s) -> str:
    """表記ゆれの吸収: 全角半角をそろえ、空白・記号・会社の種類を表す言葉を除き、英字は大文字に"""
    s = unicodedata.normalize("NFKC", str(s or "")).upper()
    s = re.sub(r"[\s・･,.\-‐ー−()（）「」『』&＆'’]", "", s)
    for x in ["株式会社", "有限会社", "合同会社", "合資会社", "(株)", "LIMITED", "LTD", "LLC", "INC", "CORPORATION", "CORP", "LP", "PTE", "PLC", "COMPANY", "CO"]:
        s = s.replace(x, "")
    return s


def load_activists() -> list[dict]:
    import yaml
    if not ACTIVISTS.exists():
        return []
    a = yaml.safe_load(ACTIVISTS.read_text(encoding="utf-8")) or {}
    out = []
    for x in a.get("activists", []):
        keys = [norm_name(n) for n in [x["name"], *x.get("aliases", [])]]
        out.append({"name": x["name"], "keys": [k for k in keys if len(k) >= 3]})
    return out


def is_activist(filer: str, acts: list[dict]) -> str | None:
    n = norm_name(filer)
    for a in acts:
        if any(k in n for k in a["keys"]):
            return a["name"]
    return None


def _csv_frames(content: bytes):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        for name in z.namelist():
            if name.endswith(".csv") and "XBRL_TO_CSV" in name:
                try:
                    df = pd.read_csv(io.BytesIO(z.read(name)), sep="\t", encoding="utf-16", dtype=str)
                except Exception:
                    continue
                if "要素ID" in df.columns:
                    df["el"] = df["要素ID"].astype(str).str.split(":").str[-1]
                    yield df


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def parse_lvh(content: bytes) -> list[dict]:
    """大量保有報告書・変更報告書(CSV): 発行者の証券コード、保有割合(共同保有者の合計)、前回の割合、提出者1の保有目的"""
    for df in _csv_frames(content):
        if not df["要素ID"].str.startswith("jplvh").any():
            continue
        top = df[df["コンテキストID"] == "FilingDateInstant"]
        def get(el, d=top):
            v = d.loc[d["el"] == el, "値"]
            return v.iloc[0] if len(v) else None
        ctx = df["コンテキストID"].astype(str)
        h1 = df[ctx.str.endswith("FilerLargeVolumeHolder1Member")]

        def ratio(el):
            """共同保有者の合計(表紙側)。提出者が1人だけの書類は合計の行が無いので、提出者ごとの値を足す"""
            v = _num(get(el))
            if v is not None:
                return v
            each = df[(df["el"] == el) & ctx.str.contains(r"FilerLargeVolumeHolder\d+Member$")].drop_duplicates("コンテキストID")
            vals = [x for x in each["値"].map(_num) if x is not None]
            return round(sum(vals), 6) if vals else None
        return [{"issuer_code": str(get("SecurityCodeOfIssuer") or "")[:4], "issuer_name": get("NameOfIssuer"),
                 "ratio": ratio("HoldingRatioOfShareCertificatesEtc"),
                 "ratio_prev": ratio("HoldingRatioOfShareCertificatesEtcPerLastReport"),
                 "duty_date": get("DateWhenFilingRequirementAroseCoverPage"),
                 "purpose": re.sub(r"\s+", " ", str(get("PurposeOfHolding", h1) or ""))[:200]}]
    return []


# ---------------------------------------------------------------------------
# 3. 有価証券報告書の「大株主の状況」
# ---------------------------------------------------------------------------
CORP_WORDS = ["会社", "(株)", "(有)", "(同)", "(資)", "(名)","銀行", "信託", "証券", "組合", "財団", "基金", "協会", "持株会", "保険", "法人", "機構", "共済", "事業団", "大学",
              "ホールディングス", "グループ", "商事", "工業", "産業", "興業", "製作所", "BANK", "TRUST", "FUND", "NOMINEE", "SECURITIES",
              "LIMITED", "LTD", "LLC", "INC", "CORP", "CO.", "L.P", "PLC", "AG", "S.A", "N.A", "GMBH", "ACCOUNT", "CLIENT", "PARTNERS"]
BREAKDOWN = {"IndividualsAndOthers": "indiv_pct", "OtherCorporations": "othercorp_pct", "FinancialInstitutions": "fin_pct",
             "ForeignersOtherThanIndividuals": "foreign_pct"}
SUM_COLS = ["docID", "code", "submit_date", "periodEnd", "top1_name", "top1_ratio", "top2_name", "top2_ratio",
            "indiv_top10", "top10_ratio", *BREAKDOWN.values()]


def is_person(name: str) -> bool:
    """個人名らしいか(会社・金融機関・ファンドを表す言葉がなく、短い)"""
    s = unicodedata.normalize("NFKC", str(name)).upper()
    return bool(s) and not any(w in s for w in CORP_WORDS) and len(s.replace(" ", "")) <= 12


def parse_holders(content: bytes) -> tuple[list[dict], dict]:
    """上位10株主(順位・名前・割合)と、株主の種類別の割合"""
    for df in _csv_frames(content):
        m = df["el"].isin(["NameMajorShareholders", "ShareholdingRatio"]) & \
            df["コンテキストID"].astype(str).str.match(r"CurrentYearInstant_No\d+MajorShareholdersMember$")
        if not m.any():
            continue
        x = df[m].assign(rank=df.loc[m, "コンテキストID"].str.extract(r"No(\d+)")[0].astype(int))
        p = x.pivot_table(index="rank", columns="el", values="値", aggfunc="first")
        rows = [{"rank": int(r), "name": re.sub(r"\s+", " ", str(v.get("NameMajorShareholders", ""))).strip(),
                 "ratio": _num(v.get("ShareholdingRatio"))} for r, v in p.iterrows()]
        br = {}
        for k, col in BREAKDOWN.items():
            v = df.loc[(df["el"] == f"PercentageOfShareholdings{k}") &
                       (df["コンテキストID"] == "CurrentYearInstant_OrdinaryShareMember"), "値"]
            br[col] = _num(v.iloc[0]) if len(v) else None
        return rows, br
    return [], {}


def holders_summary(rows: list[dict], br: dict) -> dict:
    r = sorted([x for x in rows if x["ratio"] is not None], key=lambda x: -x["ratio"])
    g = lambda i, k: r[i][k] if len(r) > i else None
    return {"top1_name": g(0, "name"), "top1_ratio": g(0, "ratio"), "top2_name": g(1, "name"), "top2_ratio": g(1, "ratio"),
            "indiv_top10": round(sum(x["ratio"] for x in r if is_person(x["name"])), 4) if r else None,
            "top10_ratio": round(sum(x["ratio"] for x in r), 4) if r else None, **br}


# ---------------------------------------------------------------------------
# 取得(途中から再開できる)
# ---------------------------------------------------------------------------
def _fetch_csv(doc_id: str, key: str) -> bytes | None:
    r = _get(f"{BASE}/documents/{doc_id}", {"type": 5, "Subscription-Key": key})
    if r is None:
        raise FetchError(doc_id)
    return r.content if r.content[:2] == b"PK" else None


def _loop(docs: list[dict], key: str, done_path, handle, sleep: float, label: str) -> int:
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    todo = [d for d in docs if d["docID"] not in done]
    log.info(f"{label}: 取得する書類 {len(todo)} 件(取得済み {len(done)} 件)")
    n, fails, t0 = 0, 0, time.time()
    with open(done_path, "a") as fd:
        for doc in todo:
            try:
                content = _fetch_csv(doc["docID"], key)
                fails = 0
            except FetchError:
                fails += 1
                log.warning(f"{doc['docID']}: 通信できず(連続 {fails} 回)")
                if fails >= 10:
                    log.error("通信できない状態が続くので止めます。時間を空けて同じコマンドで再開できます。")
                    break
                time.sleep(30 * fails)
                continue
            try:
                if content:
                    handle(doc, content)
            except Exception as e:
                log.warning(f"{doc['docID']}: {e}")
            fd.write(doc["docID"] + "\n")
            fd.flush()
            n += 1
            if n % 200 == 0:
                el = time.time() - t0
                log.info(f"{label}: {n}/{len(todo)} 件  残り約 {el / n * (len(todo) - n) / 60:.0f} 分")
            time.sleep(sleep)
    return n


def _appender(path, cols):
    new = not path.exists()
    f = open(path, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    if new:
        w.writeheader()
    return f, w


LVH_COLS = ["docID", "submit_date", "filerName", "activist", "docDescription", "issuer_code", "issuer_name", "ratio", "ratio_prev", "duty_date", "purpose"]


def build_lvh(events: pd.DataFrame, key: str, sleep: float = 0.5) -> int:
    """アクティビストが出した大量保有報告書・変更報告書・訂正の中身を取得"""
    acts = load_activists()
    e = events[events["docTypeCode"].isin(["350", "360"])].copy()
    e["activist"] = e["filerName"].map(lambda s: is_activist(s, acts))
    e = e[e["activist"].notna()]
    f, w = _appender(LVH, LVH_COLS)

    def handle(doc, content):
        for r in parse_lvh(content):
            w.writerow({**{k: doc.get(k) for k in LVH_COLS}, "submit_date": str(doc["submit_date"])[:10], **r})
        f.flush()
    try:
        return _loop(e.to_dict("records"), key, LVH_DONE, handle, sleep, "アクティビストの大量保有")
    finally:
        f.close()


def build_holders(index: pd.DataFrame, key: str, sleep: float = 0.5, limit: int | None = None) -> int:
    """有価証券報告書の大株主の状況を取得(index は edinet.load_index() の形)"""
    docs = index[index["docTypeCode"].isin(["120", "130"])].sort_values("submit_date")
    if limit:
        docs = docs.head(limit)
    fh, wh = _appender(HOLDERS, ["docID", "code", "submit_date", "rank", "name", "ratio"])
    fs, ws = _appender(HOLDERS_SUM, SUM_COLS)

    def handle(doc, content):
        rows, br = parse_holders(content)
        if not rows:
            return
        base = {"docID": doc["docID"], "code": doc["code"], "submit_date": str(doc["submit_date"])[:10]}
        for r in rows:
            wh.writerow({**base, **r})
        ws.writerow({**base, "periodEnd": doc.get("periodEnd"), **holders_summary(rows, br)})
        fh.flush()
        fs.flush()
    try:
        return _loop(docs.to_dict("records"), key, HOLDERS_DONE, handle, sleep, "大株主の状況")
    finally:
        fh.close()
        fs.close()


TOB = EDIR / "tob.csv"
TOB_DONE = EDIR / "tob_done.txt"


def parse_tob_price(content: bytes) -> float | None:
    """公開買付届出書の「買付け等の価格」の文章から、普通株式1株あたりの買付価格(円)を読み取る(数値の項目は無い)"""
    for df in _csv_frames(content):
        t = df.loc[df["el"] == "PriceOfPurchaseEtcTextBlock", "値"]
        if len(t):
            s = unicodedata.normalize("NFKC", str(t.iloc[0]))
            m = re.search(r"普通株式[^円]{0,40}?金\s*([\d,]+)\s*円", s) or re.search(r"株券[^円]{0,40}?金\s*([\d,]+)\s*円", s)
            if m:
                return float(m.group(1).replace(",", ""))
    return None


def build_tob(events: pd.DataFrame, key: str, sleep: float = 0.5) -> int:
    """公開買付届出書(240)から、対象の会社と買付価格を data/edinet/tob.csv に保存"""
    e = events[events["docTypeCode"] == "240"]
    f, w = _appender(TOB, ["docID", "submit_date", "filerName", "target", "subjectEdinetCode", "price"])

    def handle(doc, content):
        w.writerow({"docID": doc["docID"], "submit_date": str(doc["submit_date"])[:10], "filerName": doc["filerName"],
                    "target": doc.get("target"), "subjectEdinetCode": doc.get("subjectEdinetCode"), "price": parse_tob_price(content)})
        f.flush()
    try:
        return _loop(e.to_dict("records"), key, TOB_DONE, handle, sleep, "公開買付届出書")
    finally:
        f.close()


# ---------------------------------------------------------------------------
# 5. 特徴量(日付 × 銘柄。書類の提出日以降の取引日にだけ値が入る)
# ---------------------------------------------------------------------------
FIN_WORDS = ["銀行", "信託", "証券", "保険", "生命", "BANK", "TRUST", "SECURITIES", "NOMINEE", "FUND", "CUSTODY", "ACCOUNT", "CLIENT", "持株会", "共済"]
LABELS = {  # 画面・報告で使う短い名前
    "op_turn": "減益→増益", "loss_turn": "赤字→黒字", "room": "回復の途中", "margin_up": "利益率改善", "half_up": "半期増益",
    "act_new": "アクティビスト新規", "act_hold": "アクティビスト保有", "act_up": "アクティビスト買い増し", "new5": "新規5%超",
    "parent": "親子上場", "owner": "オーナー企業", "buyback": "自社株買い", "div_up": "増配",
}
# 「割安カタリスト」タブの説明(検証の結果は research/experiments/2026-11-05.md)
CATALYST_NOTE = ("<b>割安カタリスト(参考)</b>: 清原式 または 割安総合の上位30% の銘柄のうち、"
                 "<b>業績回復</b>(減益→増益・赤字→黒字・営業利益が過去5年の最高の6割以下からの増益・営業利益率の改善・半期の増益)か、"
                 "<b>割安が見直されるきっかけ</b>(アクティビストの参入・保有・買い増し、アクティビスト以外の新規5%超保有、親子上場の子会社、オーナー企業、自社株買い、増配)"
                 "の条件を1つ以上満たす銘柄。並び順は期待スコア。どれも EDINET の書類の提出日以降の数字だけを使っています。"
                 "<br><b>検証の結果</b>(2019〜2025年、上場廃止した銘柄も含む): 清原式 × 期待スコア上位5(1年後 全銘柄平均より +9.6%)に、これらの条件を足しても""成績は良くなりませんでした(減益→増益 +9.2%、自社株買い・増配 +8.2%、親子上場・オーナー企業 +5.8%、アクティビスト +10.1%)。""例外は「アクティビスト以外の新規5%超保有」(2021年11月以降で +18.5%)ですが、期間が短く件数も少ないので検証を続けています。""本番の最終候補には使っていない参考のリストです。投資判断はご自身で。")
RECOVERY = ["op_turn", "loss_turn", "room", "margin_up", "half_up"]
CATALYST = ["act_new", "act_hold", "act_up", "new5", "parent", "owner", "buyback", "div_up"]


def _event_panel(ev: pd.DataFrame, dates: pd.DatetimeIndex, codes, days: int) -> pd.DataFrame:
    """ev(列: target, submit_date)の出来事が、提出日から days 日のあいだ 1 になる表"""
    a = np.zeros((len(dates), len(codes)))
    col = {c: i for i, c in enumerate(codes)}
    ev = ev[ev["target"].isin(col)]
    pos = dates.searchsorted(ev["submit_date"].to_numpy())
    end = dates.searchsorted((ev["submit_date"] + pd.Timedelta(days=days)).to_numpy())
    for p, e_, c in zip(pos, end, ev["target"]):
        a[p:e_, col[c]] = 1.0
    return pd.DataFrame(a, index=dates, columns=codes)


def annual_recovery(f: pd.DataFrame) -> pd.DataFrame:
    """有価証券報告書ごとの業績回復の項目(f は fundamentals.doc_features の出力)"""
    a = f[f["docTypeCode"].isin(["120", "130"])].sort_values(["code", "submit_date"]) \
        .drop_duplicates(["code", "periodEnd"], keep="last").reset_index(drop=True)
    g = a.groupby("code")
    gap_ok = g["submit_date"].diff().dt.days.between(250, 500)
    prev_op, prev_g = g["op_income"].shift(1), g["op_income_g"].shift(1)
    a["op_turn"] = ((a["op_income_g"] > 0) & (prev_g < 0) & gap_ok).astype(float)       # 前期は減益、今期は増益
    a["loss_turn"] = ((a["op_income"] > 0) & (prev_op < 0) & gap_ok).astype(float)       # 営業赤字 → 黒字
    opm = a["op_income"] / a["sales"].where(a["sales"] > 0)
    a["opm_chg"] = (opm - opm.groupby(a["code"]).shift(1)).where(gap_ok).clip(-1, 1)
    a["margin_up"] = (a["opm_chg"] >= 0.02).astype(float)                                # 営業利益率が2ポイント以上改善
    mx = g["op_income"].transform(lambda s: s.rolling(5, min_periods=3).max())
    a["room_x"] = (a["op_income"] / mx).where(mx > 0)      # 今の営業利益 ÷ 過去5年(今期を含む)の最高。低いほど回復の余地が大きい
    prev_div = g["div_total"].shift(1)
    a["div_up"] = ((a["div_total"] > prev_div * 1.05) & (prev_div > 0) & gap_ok).astype(float)
    return a


def half_recovery(f: pd.DataFrame) -> pd.DataFrame:
    """半期報告書どうしの前年比(四半期報告書は取得していないので、ほぼ2025年11月以降だけ)"""
    h = f[f["docTypeCode"] == "160"].sort_values(["code", "submit_date"]).reset_index(drop=True)
    g = h.groupby("code")
    prev = g["op_income"].shift(1)
    h["half_g"] = ((h["op_income"] - prev) / prev.abs()).where(g["submit_date"].diff().dt.days.between(300, 430)).clip(-3, 3)
    h["half_up"] = (h["half_g"] > 0.1).astype(float).where(h["half_g"].notna())
    return h


def treasury_buyback(f: pd.DataFrame) -> pd.DataFrame:
    """自己株式数が前の書類より、発行済株式の0.5%以上増えた = 自社株買い(220 の書類は約1年分しか取れないので、その代わり)"""
    d = f.dropna(subset=["treasury"]).sort_values(["code", "submit_date"]).reset_index(drop=True)
    total = d["shares_filing"].fillna(d["shares"])
    g = d.groupby("code")
    inc = (d["treasury"] - g["treasury"].shift(1)) / total
    ok = g["submit_date"].diff().dt.days.between(100, 500)
    same = (total / total.groupby(d["code"]).shift(1)).between(0.9, 1.1)      # 分割・併合の前後は比べない
    d["buyback"] = ((inc >= 0.005) & ok & same).astype(float)
    return d


def holder_flags(hs: pd.DataFrame, listed_names: set) -> pd.DataFrame:
    """大株主の要約 → 親子上場(筆頭株主が上場会社で30%以上)・オーナー企業(個人と資産管理会社らしき株主が大きい)"""
    h = hs.copy()
    n1 = h["top1_name"].map(norm_name)
    h["parent"] = ((h["top1_ratio"] >= 0.30) & n1.isin(listed_names)).astype(float)
    up = h["top1_name"].fillna("").astype(str).map(lambda s: unicodedata.normalize("NFKC", str(s)).upper())
    private_corp = ~n1.isin(listed_names) & ~up.map(lambda s: any(w in s for w in FIN_WORDS)) & ~h["top1_name"].map(is_person)
    # 個人の上位10株主の合計が15%以上、または 上場していない事業会社(資産管理会社らしい)が筆頭で15%以上 かつ 個人の大株主もいる
    h["owner"] = ((h["indiv_top10"] >= 0.15) | (private_corp & (h["top1_ratio"] >= 0.15) & (h["indiv_top10"] >= 0.02))).astype(float)
    h.loc[h["parent"] == 1, "owner"] = 0.0
    return h


def activist_panels(dates: pd.DatetimeIndex, codes, ev: pd.DataFrame) -> dict[str, pd.DataFrame]:
    acts = load_activists()
    big = ev[ev["docTypeCode"].isin(["350", "360"])].dropna(subset=["target"]).copy()
    big["activist"] = big["filerName"].map(lambda s: is_activist(s, acts))
    desc = big["docDescription"].fillna("")
    new = desc.str.startswith("大量保有報告書")
    inst = desc.str.contains("特例")             # 特例対象株券等 = 銀行・運用会社などの機関投資家
    out = {"new5": _event_panel(big[new & ~inst & big["activist"].isna()], dates, codes, 180),
           "act_new": _event_panel(big[new & big["activist"].notna()], dates, codes, 365)}
    hold = np.zeros((len(dates), len(codes)))
    up = np.zeros((len(dates), len(codes)))
    col = {c: i for i, c in enumerate(codes)}
    if LVH.exists():
        lv = pd.read_csv(LVH, dtype={"issuer_code": str, "docID": str})
        lv["submit_date"] = pd.to_datetime(lv["submit_date"])
        lv["target"] = lv["issuer_code"].str[:4]
        # 保有継続中: そのアクティビストの最新の報告の保有割合が5%以上(5%未満の報告 = 売却)。次の報告まで、最長2年引き継ぐ
        for (_, tgt), g in lv.sort_values("submit_date").groupby(["activist", "target"]):
            if tgt not in col:
                continue
            sd = g["submit_date"].tolist()
            for k, r in enumerate(g.itertuples()):
                p = dates.searchsorted(r.submit_date)
                stop = min(sd[k + 1] if k + 1 < len(sd) else r.submit_date + pd.Timedelta(days=730), r.submit_date + pd.Timedelta(days=730))
                if r.ratio >= 0.05:
                    hold[p:dates.searchsorted(stop), col[tgt]] = 1.0
                if pd.notna(r.ratio_prev) and r.ratio > r.ratio_prev:
                    up[p:dates.searchsorted(r.submit_date + pd.Timedelta(days=365)), col[tgt]] = 1.0
    out["act_hold"] = pd.DataFrame(np.maximum(hold, out["act_new"].to_numpy()), index=dates, columns=codes)
    out["act_up"] = pd.DataFrame(up, index=dates, columns=codes)
    return out


def catalyst_panels(f: pd.DataFrame, dates: pd.DatetimeIndex, codes, universe: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """業績回復・カタリストの日次パネル。f は fundamentals.doc_features の出力。データが無い項目は入らない"""
    from .fundamentals import _to_daily
    out = {}
    a = annual_recovery(f)
    for c in ["op_turn", "loss_turn", "margin_up", "room_x", "div_up", "opm_chg"]:
        out[c] = _to_daily(a, c, dates, codes, max_age=300)
    out["room"] = (out["room_x"] <= 0.6).astype(float).where(out["room_x"].notna())   # 営業利益が過去5年の最高の6割以下
    hf = half_recovery(f)
    for c in ["half_up", "half_g"]:
        out[c] = _to_daily(hf, c, dates, codes, max_age=200)
    out["buyback"] = _to_daily(treasury_buyback(f), "buyback", dates, codes, max_age=250)
    if EVENTS.exists():
        ev = load_events()
        bb = ev[ev["docTypeCode"] == "220"].dropna(subset=["target"])
        out["buyback"] = out["buyback"].fillna(0).clip(lower=_event_panel(bb, dates, codes, 180))   # 直近1年は自己株券買付状況報告書も
        out.update(activist_panels(dates, codes, ev))
    if HOLDERS_SUM.exists():
        hs = pd.read_csv(HOLDERS_SUM, dtype={"code": str, "docID": str})
        hs["submit_date"] = pd.to_datetime(hs["submit_date"])
        listed = set(load_codes()["name"].dropna().map(norm_name)) | set(universe["name"].map(norm_name))
        hf2 = holder_flags(hs, listed)
        for c in ["parent", "owner"]:
            out[c] = _to_daily(hf2, c, dates, codes, max_age=300)
    return out


def catalyst_candidates(today: pd.DataFrame, w, universe: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """割安カタリスト: 清原式 または 割安総合の上位30% で、業績回復かカタリストの条件を1つ以上満たす銘柄(期待スコア順)"""
    from .fundamentals import doc_features, load_splits, load_tidy
    t = today.copy()
    d = t["date"].iloc[0]
    dates = w.elig.index[w.elig.index <= d]
    P = catalyst_panels(doc_features(load_tidy(), load_splits()), dates, w.elig.columns, universe)
    row = {k: v.iloc[-1].reindex(t.index) for k, v in P.items()}
    prof = t["PER"] > 0
    v = t[prof].copy()
    for c, asc in [("NCR", True), ("PER", False), ("PBR", False), ("DY", True)]:
        v["r_" + c] = v[c].rank(pct=True, ascending=asc)
    vs = v[["r_NCR", "r_PER", "r_PBR", "r_DY"]].mean(axis=1).rank(pct=True)
    base = ((t["NCR"] >= 1) & prof) | vs.reindex(t.index).ge(0.7)
    oig = w.feat["OIg"].loc[d].reindex(t.index)
    flags = pd.DataFrame(index=t.index)
    for k in ["op_turn", "loss_turn", "margin_up", "half_up", "act_new", "act_hold", "act_up", "new5", "parent", "owner", "buyback", "div_up"]:
        if k in row:
            flags[k] = row[k] == 1
    if "room_x" in row:
        flags["room"] = (row["room_x"] <= 0.6) & (oig > 0)         # 過去5年の最高の6割以下で、増益(回復の途中)
    t["room_x"] = row.get("room_x")
    t["flags"] = flags.apply(lambda r: "・".join(LABELS[k] for k in flags.columns if r[k]), axis=1)
    t["n_flags"] = flags.sum(axis=1)
    t["kiyoshi"] = (t["NCR"] >= 1) & prof
    out = t[base & (t["n_flags"] > 0)]
    return out.sort_values("score", ascending=False).head(n)
