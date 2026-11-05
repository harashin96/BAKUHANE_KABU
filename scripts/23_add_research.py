"""Claude の定性調査の結果を research/qualitative.csv に追記する(週1回のスケジュール実行から使う)

    python scripts/23_add_research.py research/inbox.json

inbox.json は次の形のリスト(1銘柄1件):
    [{"code": "1234", "name": "...", "rank": 1, "price": 1234,
      "grade": "A", "confidence": "中", "drop": "巻き込まれ", "summary": "一言の理由",
      "good": "買い材料", "risk": "リスク", "sources": "URL; URL",
      # 割安カタリストの候補だけ(省略可)
      "catalyst": "カタリストの中身と、起きる可能性・時期", "recovery": "業績回復の根拠",
      "scenarios": "大きく見直される 30% 2500円 / 一部 40% 1800円 / 何も起きない 30% 1300円", "ev_pct": 35.0, "priced_in": "織り込み度"}]
date は省略すると今日。同じ日・同じ銘柄は上書き。
"""
import json
import sys
from datetime import date

import _bootstrap  # noqa: F401
import pandas as pd

from jpstocks.research import COLUMNS, DROP, RESEARCH

src = sys.argv[1]
items = json.loads(open(src, encoding="utf-8").read())
bad = [x.get("code") for x in items if x.get("grade") not in ("A", "B", "C") or x.get("confidence") not in ("高", "中", "低")
       or x.get("drop") not in DROP]
bad += [x.get("code") for x in items if x.get("ev_pct") not in (None, "") and not isinstance(x.get("ev_pct"), (int, float))]
if bad:
    raise SystemExit(f"grade は A/B/C、confidence は 高/中/低、drop は {'/'.join(DROP)} 、ev_pct は数値(期待値%)にしてください: {bad}")
new = pd.DataFrame(items)
new["date"] = new.get("date", pd.Series(dtype=str)).fillna(str(date.today())) if "date" in new else str(date.today())
new["code"] = new["code"].astype(str)
new = new.reindex(columns=COLUMNS)
RESEARCH.parent.mkdir(exist_ok=True)
old = pd.read_csv(RESEARCH, dtype={"code": str}) if RESEARCH.exists() else pd.DataFrame(columns=COLUMNS)
allr = pd.concat([old, new], ignore_index=True).drop_duplicates(["date", "code"], keep="last").sort_values(["date", "rank"]).reindex(columns=COLUMNS)
allr.to_csv(RESEARCH, index=False, encoding="utf-8")
print(f"{len(new)} 件を追記(合計 {len(allr)} 件): " + " ".join(f"{c}={g}" for c, g in zip(new["code"], new["grade"])))
