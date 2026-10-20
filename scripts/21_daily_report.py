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
import numpy as np
import pandas as pd

from jpstocks.config import load_config, setup_logging
from jpstocks.data import fetch_prices, load_prices, load_universe
from jpstocks.jump import build_world, dip_candidates, load_model, market_status, score_day
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
            for c in ["submit_date", "periodEnd"]:   # 既存のファイルと同じ「YYYY-MM-DD」にそろえる
                new[c] = pd.to_datetime(new[c], errors="coerce").dt.strftime("%Y-%m-%d")
            T = E.EDIR / "fund_tidy.csv"
            old = pd.read_csv(T, dtype=str)
            for c in ["submit_date", "periodEnd"]:
                old[c] = old[c].astype(str).str[:10]
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
# 最新日の対象銘柄数を確認(データがそろっていない日は、そろっている直近の日を使う)
cnt = w.elig.sum(axis=1)
medval = w.m.value.iloc[-40:].rolling(20, min_periods=15).median()
for d in w.elig.index[-5:]:
    k = w.elig.index.get_loc(d)
    px_ok = int(w.m.close.loc[d].notna().sum())
    val = medval.loc[d] if d in medval.index else pd.Series(dtype=float)
    log.info(f"  {d.date()}: 対象 {int(cnt.loc[d])} 銘柄 / 終値あり {px_ok} / 売買代金3千万以上 {int((val >= 0.3e8).sum())} / "
             f"時価総額あり {int(w.P['mcap'].loc[d].notna().sum())} / 純資産あり {int(w.P['equity'].loc[d].gt(0).sum())}")
ok = np.flatnonzero(cnt.to_numpy() >= 100)
if len(ok) == 0:
    raise SystemExit("対象銘柄が100未満の日しかありません。ログの内訳を確認してください。")
i_use = int(ok[-1])
if i_use != len(cnt) - 1:
    log.warning(f"最新日 {w.elig.index[-1].date()} はデータがそろっていないため、{w.elig.index[i_use].date()} 時点でランキングを作ります")
today = score_day(w, bundle, i=i_use)
top, dropped, hist = update_history(today, top_n)
status = market_status(w, i_use)
log.info(f"相場のお得度: {status['level']} ({status['score']:.0f})")
path = write_report(today, top, dropped, w, bundle, track_record(hist, w), budget, stop, rc.get("publish_dir") or "",
                    market=status, dips=dip_candidates(today, status))
log.info(f"完了 ({time.time()-t0:.0f}秒): {path}")
print(top[["p_jump", "p_crash", "price", "days_in"]].head(10).round(3).to_string())
if not a.no_open:
    try:
        os.startfile(path)  # Windows: ブラウザで開く
    except Exception:
        pass
