"""定性調査で今回調べる銘柄を選ぶ(スケジュール実行の Claude が使う。毎回その場でスクリプトを書かなくて済むように)

    python scripts/24_research_targets.py            # 最大15銘柄を選び、logs/research_targets.json に書いて表で表示

選び方(research/weekly_prompt.md の 3 と同じ。調査日は research/qualitative.csv の最後の日付):
  1. 最終候補(picks_short・picks_long)で、3日以上前に調べた or 未調査
  2. 候補(candidates・long_candidates・catalyst_candidates)で、7日以上前に調べた or 未調査(3つのリストから順番に1つずつ)
  3. 残りの枠: stocks.json の全銘柄を順位の小さい順に、30日以上前に調べた or 未調査
  今日すでに調べた銘柄は選ばない。
"""
import json
import sys
from datetime import date

import _bootstrap  # noqa: F401
import pandas as pd
import requests

from jpstocks.config import ROOT
from jpstocks.research import RESEARCH

SITE = "https://harashin96.github.io/BAKUHANE_KABU/"
MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 15
today = pd.Timestamp(date.today())


def get(name):
    r = requests.get(SITE + name, params={"t": int(today.timestamp())}, timeout=60)
    r.raise_for_status()
    return r.json()


top, st = get("top.json"), get("stocks.json")
fields = st["fields"]
allst = {c: dict(zip(fields, v)) for c, v in st["stocks"].items()}
q = pd.read_csv(RESEARCH, dtype={"code": str}) if RESEARCH.exists() else pd.DataFrame(columns=["date", "code", "grade"])
q["date"] = pd.to_datetime(q["date"])
last = q.sort_values("date").groupby("code").tail(1).set_index("code")


def age(c):
    return None if c not in last.index else (today - last.loc[c, "date"]).days


sel, why = [], {}


def add(c, reason):
    c = str(c)
    if c in why or len(sel) >= MAX:
        return
    a = age(c)
    if a == 0:          # 今日すでに調べた
        return
    sel.append(c)
    why[c] = reason


# 1. 最終候補
for c in top.get("picks_short", []) + top.get("picks_long", []):
    a = age(str(c))
    if a is None or a >= 3:
        add(c, "最終候補")
# 2. 候補(3つのリストから順番に1つずつ)
lists = [("3か月の候補", top.get("candidates", [])), ("長期の候補", top.get("long_candidates", [])),
         ("割安カタリスト", top.get("catalyst_candidates", []))]
for k in range(max((len(x) for _, x in lists), default=0)):
    for name, lst in lists:
        if k < len(lst):
            c = str(lst[k]["code"])
            a = age(c)
            if a is None or a >= 7:
                add(c, name)
# 3. 残りの枠: 全銘柄を順位の小さい順に
ranked = sorted((c for c, v in allst.items() if v.get("rank") is not None), key=lambda c: allst[c]["rank"])
for c in ranked:
    if len(sel) >= MAX:
        break
    a = age(c)
    if a is None or a >= 30:
        add(c, "評価の対象を広げる")

in_list = {}
for name, lst in lists:
    for x in lst:
        in_list.setdefault(str(x["code"]), []).append(name)
cat = {str(x["code"]): x for x in top.get("catalyst_candidates", [])}
picks_long = set(map(str, top.get("picks_long", [])))
out = []
for c in sel:
    v = allst.get(c, {})
    ls = in_list.get(c, [])
    long_only = (c in picks_long or "長期の候補" in ls or "割安カタリスト" in ls) and "3か月の候補" not in ls and c not in set(map(str, top.get("picks_short", [])))
    out.append({"code": c, "name": v.get("name"), "sector": v.get("sector"), "rank": v.get("rank"), "price": v.get("price"),
                "ret1m_pct": v.get("RET1M"), "PER": v.get("PER"), "PBR": v.get("PBR"), "DY": v.get("DY"), "NCR": v.get("NCR"),
                "reason": why[c], "lists": ls, "horizon": "1年" if long_only else "3か月",
                "catalyst": c in cat, "flags": cat[c].get("flags") if c in cat else None,
                "last_date": None if c not in last.index else str(last.loc[c, "date"].date()),
                "last_grade": None if c not in last.index else last.loc[c, "grade"]})
p = ROOT / "logs" / "research_targets.json"   # logs/ は git に入らない
p.parent.mkdir(exist_ok=True)
p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{top.get('date')} のランキングから {len(out)} 銘柄を選びました → logs/research_targets.json(詳しい項目)")
for x in out:
    print(f"{x['code']} {x['name']} 順位{x['rank']} {x['reason']} 判断:{x['horizon']} カタリスト:{'あり' if x['catalyst'] else '−'} "
          f"前回:{x['last_date'] or '未調査'} {x['last_grade'] or ''}")
