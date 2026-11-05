"""検証用の「上場廃止した銘柄も含む」データ: 株価は J-Quants、財務は EDINET(今の銘柄 + 上場廃止した会社)

本番(yfinance、今上場している銘柄だけ)との違い:
- TOB・MBO・経営破綻などで上場廃止になった銘柄も、上場していた期間は対象に入る
- 上場廃止の後は、最後の株価のまま現金で持っていたことにする(fwd_prices)。TOB なら最後の株価 ≒ 買付価格
- J-Quants の調整後株価は分割だけを調整し、配当は含まない(yfinance の調整後終値は配当も含む)。
  そのため全銘柄平均との差は、配当の多い割安株ほど本番の検証より少し小さく出る(比べるときは同じデータの中で比べる)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from jpstocks import jquants as J

DELISTED_TIDY = ROOT.parent / "data" / "delisted" / "fund_tidy.csv"


def jq_prices() -> pd.DataFrame:
    """yfinance と同じく「分割を調整済み」の株価にそろえる(close も調整後。未調整の C を混ぜると、
    clean_split_artifacts が分割を二重に調整してしまう)。出来高も調整後、売買代金は変わらない"""
    b = J.load("bars", ["Date", "Code", "AdjO", "AdjC", "AdjVo"])
    b = b[b["Code"].str.len() == 5]
    out = pd.DataFrame({"date": pd.to_datetime(b["Date"]), "code": b["Code"].str[:4]})
    for c, s in [("open", "AdjO"), ("close", "AdjC"), ("adj_close", "AdjC"), ("volume", "AdjVo")]:
        out[c] = pd.to_numeric(b[s], errors="coerce").replace(0, np.nan) if c != "volume" else pd.to_numeric(b[s], errors="coerce")
    return out.dropna(subset=["close"]).drop_duplicates(["code", "date"])


def jq_universe() -> pd.DataFrame:
    """銘柄一覧(月初のスナップショットを全部つなげ、銘柄ごとに最後の情報)。国内の普通株(ProdCat 011)だけ"""
    m = J.load("master")
    m = m[m["ProdCat"] == "011"].sort_values("Date")
    u = m.drop_duplicates("Code", keep="last")
    return pd.DataFrame({"code": u["Code"].str[:4], "name": u["CoName"], "market": u["MktNm"],
                         "sector33": u["S33Nm"], "sector17": u["S17Nm"], "last_listed": u["Date"]}).reset_index(drop=True)


def all_tidy() -> pd.DataFrame:
    from jpstocks.fundamentals import load_tidy
    a = load_tidy()
    if DELISTED_TIDY.exists():
        a = pd.concat([a, load_tidy(DELISTED_TIDY)], ignore_index=True).drop_duplicates("docID")
    return a.sort_values(["code", "submit_date"]).reset_index(drop=True)


def make_world(since="2016-11-07"):
    """上場廃止した銘柄も含む World(jpstocks.jump.build_world を、財務の読み込みだけ差し替えて使う)"""
    import jpstocks.jump as JM
    JM.load_tidy = all_tidy
    uni = jq_universe()
    w = JM.build_world(jq_prices(), uni, since=since)
    return w, uni


def fwd_prices(w) -> pd.DataFrame:
    """将来のリターン用の株価: 上場廃止の後は最後の株価のまま(現金化したとみなす)"""
    return w.m.adj_close.reindex(w.elig.index).ffill()
