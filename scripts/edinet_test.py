"""EDINETのAPIキーが使えるか確認(1回だけ通信)

    python scripts/edinet_test.py
"""
from datetime import date, timedelta

import _bootstrap  # noqa: F401

from jpstocks.edinet import api_key, list_documents

d = date.today() - timedelta(days=1)
while d.weekday() >= 5:
    d -= timedelta(days=1)
rows = list_documents(d, api_key())
yuho = [r for r in rows if r.get("docTypeCode") in ("120", "160") and r.get("secCode")]
print(f"OK: {d} の提出書類 {len(rows)} 件(うち上場企業の有報・半期報告書 {len(yuho)} 件)")
for r in yuho[:5]:
    print(" ", r["secCode"], r["filerName"], r["docDescription"])
