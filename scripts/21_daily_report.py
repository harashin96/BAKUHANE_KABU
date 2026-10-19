"""毎日の「爆ハネ期待値ランキング」を作る(株価とEDINETを更新 → 採点 → reports/latest.html)

    python scripts/21_daily_report.py              # 更新してからランキングを作る(平日の夕方〜夜に)
    python scripts/21_daily_report.py --no-update  # 手元のデータだけでランキングを作る

設定: config/settings.yaml の report: 欄(表示する銘柄数・1銘柄の予算・損切り目安)
保有銘柄: config/my_positions.csv に書くと、売り時(3か月経過・損切りライン)も表示
"""
import argparse
import os
import time
from datetime import date, timedelta

import _bootstrap  # noqa: F401
import pandas as pd

from jpstocks.config import load_config, setup_logging
from jpstocks.data import fetch_prices, load_prices, load_universe
from jpstocks.jump import build_world, load_model, score_day
from jpstocks.report import track_record, update_history, write_report

ap = argparse.ArgumentParser()
ap.add_argument("--no-update", action="store_true")
ap.add_argument("--no-open", action="store_true")
a = ap.parse_args()
log = setup_logging("daily")
cfg = load_config()
rc = cfg.get("report", {})
top_n = int(rc.get("top_n", 30))
budget = float(rc.get("budget_per_stock", 340000))
stop = float(rc.get("stop_loss", -0.20))
t0 = time.time()
uni = load_universe()

if not a.no_update:
    d = cfg["data"]
    log.info("1/3 株価を更新")
    fetch_prices(uni["ticker"].tolist(), d["start"], d["chunk"], d["sleep_sec"], update=True, write_csv=False)
    log.info("2/3 EDINET(新しく出た有価証券報告書・半期報告書)を更新")
    try:
        from jpstocks import edinet as E
        key = E.api_key()
        E.build_index(date.today() - timedelta(days=14), date.today(), key)
        idx = E.load_index()
        idx = idx[idx["docTypeCode"].isin(["120", "130", "160"]) & (idx["withdrawalStatus"].fillna("0") == "0")]
        idx = idx[idx["code"].isin(set(uni["code"].astype(str)))]
        rows = []
        n = E.build_fundamentals(idx, key, collect=rows)
        if rows:
            new = E.tidy_fundamentals(pd.DataFrame(rows).astype(str))
            T = E.EDIR / "fund_tidy.csv"
            old = pd.read_csv(T, dtype={"code": str, "docTypeCode": str})
            allt = pd.concat([old, new.astype({"code": str, "docTypeCode": str})], ignore_index=True).drop_duplicates("docID", keep="last")
            allt.to_csv(T, index=False)
            log.info(f"財務データを追加: {len(new)} 書類")
        else:
            log.info(f"新しい書類はありません(確認 {n} 件)")
    except Exception as e:
        log.warning(f"EDINETの更新に失敗(前回までのデータで続けます): {e}")

log.info("3/3 採点してレポートを作成")
prices = load_prices()
since = (prices["date"].max() - pd.Timedelta(days=700)).strftime("%Y-%m-%d")
w = build_world(prices, uni, since=since)
bundle = load_model()
today = score_day(w, bundle)
top, dropped, hist = update_history(today, top_n)
path = write_report(today, top, dropped, w, bundle, track_record(hist, w), budget, stop, rc.get("publish_dir") or "")
log.info(f"完了 ({time.time()-t0:.0f}秒): {path}")
print(top[["p_jump", "p_crash", "price", "days_in"]].head(10).round(3).to_string())
if not a.no_open:
    try:
        os.startfile(path)  # Windows: ブラウザで開く
    except Exception:
        pass
