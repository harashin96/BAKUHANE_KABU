"""STEP 7: J-Quants から株価(上場廃止した銘柄も含む)・決算短信の数字・銘柄一覧を取得(途中で止めても続きから再開)

    python scripts/07_fetch_jquants.py                    # 2016-11-07(スタンダードの10年分の始まり)から今日まで。初回は1〜2時間
    python scripts/07_fetch_jquants.py --kinds fins       # 決算短信だけ
"""
import _bootstrap  # noqa: F401

import argparse
from datetime import date

from jpstocks import jquants as J
from jpstocks.config import setup_logging

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2016-11-07")
ap.add_argument("--kinds", default="master,fins,bars")
a = ap.parse_args()
setup_logging("jquants")
key = J.api_key()
for kind in a.kinds.split(","):
    n = J.fetch_by_date(kind, date.fromisoformat(a.start), date.today(), key)
    print(f"{kind}: {n} 日分を取得")
