"""毎日の「爆ハネ期待値ランキング」レポート(HTML / CSV)"""
from __future__ import annotations

import html
import logging

import numpy as np
import pandas as pd

from .config import ROOT
from .jump import H

log = logging.getLogger("jpstocks")
REPORTS = ROOT / "reports"
HISTORY = REPORTS / "rank_history.csv"
POSITIONS = ROOT / "config" / "my_positions.csv"


def _bday_after(d: pd.Timestamp, n: int) -> pd.Timestamp:
    return (pd.Timestamp(d) + pd.offsets.BDay(n)).normalize()


def update_history(today: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """今日の上位を履歴に追加し、各銘柄が「いつランキング入りしたか」を付ける"""
    REPORTS.mkdir(exist_ok=True)
    d = pd.Timestamp(today["date"].iloc[0])
    top = today.head(top_n).copy()
    top["rank"] = np.arange(1, len(top) + 1)
    hist = pd.read_csv(HISTORY, dtype={"code": str}, parse_dates=["date"]) if HISTORY.exists() else pd.DataFrame()
    if len(hist):
        hist = hist[hist["date"] != d]
    rows = top.reset_index().rename(columns={"index": "code"})[["code", "rank", "score", "p_jump", "p_crash", "price"]]
    rows.insert(0, "date", d)
    hist = pd.concat([hist, rows], ignore_index=True).sort_values(["date", "rank"])
    hist.to_csv(HISTORY, index=False)
    # 連続してランキングに入っている期間の初日 = ランクイン日
    days = sorted(hist["date"].unique())
    pos = {x: k for k, x in enumerate(days)}
    entry = {}
    for code in top.index:
        h = hist[hist["code"] == code].sort_values("date")
        ks = [pos[x] for x in h["date"]]
        start = len(ks) - 1
        while start > 0 and ks[start - 1] == ks[start] - 1:
            start -= 1
        r0 = h.iloc[start]
        entry[code] = (r0["date"], r0["price"], len(ks) - start)
    top["entry_date"] = [entry[c][0] for c in top.index]
    top["entry_price"] = [entry[c][1] for c in top.index]
    top["days_in"] = [entry[c][2] for c in top.index]
    prev_codes = set(hist.loc[hist["date"] == days[-2], "code"]) if len(days) >= 2 else set()
    dropped = sorted(prev_codes - set(top.index))
    return top, dropped, hist


def track_record(hist: pd.DataFrame, w) -> pd.DataFrame | None:
    """過去にランキング入りした銘柄の、その後3か月の成績(全対象銘柄の平均と比較)"""
    if hist.empty:
        return None
    ao = w.m.adj_open
    dates = ao.index
    rows = []
    ent = []   # 連続してランキングに入っている期間の初日(ランクイン日)ごとに1件
    for code, h in hist.groupby("code"):
        ds = sorted(h["date"])
        prev = None
        for d in ds:
            k = dates.searchsorted(d)
            if prev is None or k - prev > 1:
                ent.append((d, code))
            prev = k
    for d, code in ent:
        k = dates.searchsorted(d)
        if k + 1 + H >= len(dates) or code not in ao.columns:
            continue
        r = ao[code].iloc[k + 1 + H] / ao[code].iloc[k + 1] - 1
        if d in w.elig.index:
            e = w.elig.loc[d]
            allr = (ao.iloc[k + 1 + H][e[e].index] / ao.iloc[k + 1][e[e].index] - 1).mean()
        else:
            allr = np.nan
        rows.append({"date": d, "code": code, "ret": r, "bench": allr})
    if not rows:
        return None
    return pd.DataFrame(rows)


def load_positions() -> pd.DataFrame | None:
    if not POSITIONS.exists():
        return None
    p = pd.read_csv(POSITIONS, dtype={"code": str}, comment="#", parse_dates=["buy_date"])
    return p if len(p) else None


def _fmt(x, f="{:.1f}"):
    return "" if pd.isna(x) else f.format(x)


def write_report(today: pd.DataFrame, top: pd.DataFrame, dropped: list, w, bundle: dict, track: pd.DataFrame | None,
                 budget: float, stop_loss: float, publish_dir: str = "") -> str:
    d = pd.Timestamp(today["date"].iloc[0])
    names = w.universe.set_index(w.universe["code"].astype(str))
    def nm(c):
        return names["name"].get(c, "?") if c in names.index else "?"
    def sec(c):
        return names["sector33"].get(c, "") if c in names.index else ""

    rows_html = []
    for k, (code, r) in enumerate(top.iterrows(), 1):
        new = r["days_in"] == 1
        status = '<span class="buy">買い時(新規ランクイン)</span>' if new else f'継続 {int(r["days_in"])}日目'
        cost100 = r["price"] * 100
        afford = "" if cost100 <= budget else ' <span class="warn">予算超(S株なら可)</span>'
        sell_day = _bday_after(r["entry_date"], H)
        stop = r["entry_price"] * (1 + stop_loss)
        rows_html.append(f"""<tr class="{'new' if new else ''}">
<td>{k}</td><td><a href="https://kabutan.jp/stock/?code={code}" target="_blank">{code}</a></td>
<td class="name">{html.escape(str(nm(code)))}<div class="sec">{html.escape(str(sec(code)))}</div></td>
<td class="num"><b>{r['p_jump']*100:.0f}%</b></td><td class="num">{r['p_crash']*100:.0f}%</td>
<td>{status}</td>
<td class="num">{r['price']:,.0f}</td><td class="num">{cost100/1e4:,.1f}万{afford}</td>
<td>{pd.Timestamp(r['entry_date']).date()}<div class="sec">@{r['entry_price']:,.0f}円</div></td>
<td>{sell_day.date()}</td><td class="num">{stop:,.0f}</td>
<td class="num">{_fmt(r['PER'])}</td><td class="num">{_fmt(r['PBR'],'{:.2f}')}</td><td class="num">{_fmt(r['NCR'],'{:.2f}')}</td>
<td class="num">{r['mcap_oku']:,.0f}</td><td class="num">{_fmt(r['RET1M'],'{:+.0f}')}%</td><td class="num">{_fmt(r['HI52'],'{:.0f}')}%</td>
<td class="num">{_fmt(r['VOLSURGE'],'{:.1f}')}倍</td><td class="num">{_fmt(r['VOL60'],'{:.0f}')}%</td>
</tr>""")

    # 保有銘柄
    pos = load_positions()
    pos_html = ""
    if pos is not None:
        prow = []
        for _, p in pos.iterrows():
            c = str(p["code"])
            cur = w.m.close[c].dropna().iloc[-1] if c in w.m.close.columns else np.nan
            pl = cur / p["buy_price"] - 1
            due = _bday_after(p["buy_date"], H)
            rank = (list(today.index).index(c) + 1) if c in today.index else None
            if pl <= stop_loss:
                act = '<span class="sell">損切りライン到達</span>'
            elif d >= due:
                act = '<span class="sell">3か月経過: 売り時</span>'
            else:
                act = f"保有継続(あと{np.busday_count(d.date(), due.date())}営業日)"
            prow.append(f"<tr><td>{c}</td><td>{html.escape(str(nm(c)))}</td><td>{pd.Timestamp(p['buy_date']).date()}</td>"
                        f"<td class='num'>{p['buy_price']:,.0f}</td><td class='num'>{cur:,.0f}</td><td class='num'>{pl*100:+.1f}%</td>"
                        f"<td>{due.date()}</td><td class='num'>{p['buy_price']*(1+stop_loss):,.0f}</td>"
                        f"<td class='num'>{rank or '圏外'}</td><td>{act}</td></tr>")
        pos_html = f"""<h2>保有中の銘柄(config/my_positions.csv)</h2>
<table><tr><th>コード</th><th>銘柄</th><th>買った日</th><th>買値</th><th>現在値</th><th>損益</th><th>3か月後(売り時)</th><th>損切り目安</th><th>今日の順位</th><th>判定</th></tr>
{''.join(prow)}</table>"""

    drop_html = ""
    if dropped:
        drop_html = "<p class='note'>昨日からランキング圏外になった銘柄: " + "、".join(
            f"{c} {html.escape(str(nm(c)))}" for c in dropped) + "(売りの合図ではありません。買った銘柄は3か月保有が基本)</p>"

    track_html = ""
    if track is not None and len(track):
        t = track.dropna()
        if len(t):
            track_html = (f"<h2>このランキングの実績(ランクイン後3か月)</h2><p>対象 {len(t)} 件: 平均 {t.ret.mean()*100:+.1f}% "
                          f"(同じ期間の全対象銘柄の平均 {t.bench.mean()*100:+.1f}%) / 爆ハネ(+30%以上) {(t.ret>=0.3).mean()*100:.0f}% / "
                          f"-30%以下 {(t.ret<=-0.3).mean()*100:.0f}%</p>")

    base_j, base_c = bundle["base_jump"] * 100, bundle["base_crash"] * 100
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>爆ハネ期待値ランキング {d.date()}</title>
<style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--line:#e3e2dc;--acc:#0b6e4f;--warn:#b54708;--sell:#b42318;--hl:#eaf6ef}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#ecebe6;--mut:#a3a29b;--line:#33332f;--acc:#4cc38a;--warn:#f0a35e;--sell:#f97066;--hl:#1d2b23}}}}
body{{background:var(--bg);color:var(--fg);font-family:"Hiragino Sans","Yu Gothic UI","Meiryo",sans-serif;margin:0;padding:16px 20px;font-size:14px}}
h1{{font-size:20px;margin:4px 0}} h2{{font-size:16px;margin:24px 0 8px}}
.note{{color:var(--mut);font-size:12.5px;line-height:1.6;max-width:1100px}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;white-space:nowrap}}
th,td{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
th{{font-size:12px;color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--bg)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}} .name{{min-width:150px;max-width:220px;white-space:normal}}
.sec{{font-size:11px;color:var(--mut)}} tr.new{{background:var(--hl)}} a{{color:var(--acc)}}
.buy{{color:var(--acc);font-weight:700}} .warn{{color:var(--warn);font-size:11px}} .sell{{color:var(--sell);font-weight:700}}
</style></head><body>
<h1>爆ハネ期待値ランキング <span style="color:var(--mut);font-weight:400">{d.date()} 終値時点</span></h1>
<p class="note">作成: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}(平日18:30ごろ自動更新)</p>
<p class="note">並び順 = 「3か月以内に+30%以上(爆ハネ)の確率」−「3か月以内に-30%以下(暴落)の確率」。全銘柄の平均は 爆ハネ {base_j:.0f}% / 暴落 {base_c:.0f}%。<br>
<b>使い方</b>: 「買い時(新規ランクイン)」の銘柄を翌営業日の寄り付きで買い、<b>約3か月(63営業日)保有</b>が検証で最も良かった方法です。
損切り目安({stop_loss*100:.0f}%)は任意: 平均リターンは少し下がるが、大きな損を防ぐ。
過去の検証(2019〜2025年)では上位20銘柄の3か月リターンが全銘柄平均より約+2.8%高かった一方、1銘柄ずつでは中央値は+1%程度で、3〜4銘柄に1つが大きく跳ねる分布です。<b>数銘柄に分けて買う</b>ことを前提にしてください。投資判断はご自身で。</p>
{pos_html}
<h2>ランキング 上位{len(top)}銘柄</h2>
<div class="wrap"><table>
<tr><th>#</th><th>コード</th><th>銘柄</th><th>爆ハネ確率</th><th>暴落確率</th><th>買い時</th><th>株価</th><th>100株</th><th>ランクイン</th><th>売り時の目安</th><th>損切り目安</th>
<th>PER</th><th>PBR</th><th>ネットキャッシュ比率</th><th>時価総額(億)</th><th>1か月</th><th>52週高値比</th><th>出来高(直近/平常)</th><th>年ボラ</th></tr>
{''.join(rows_html)}
</table></div>
{drop_html}
{track_html}
<p class="note">モデル: {bundle['trained_until']} までのデータで学習(サンプル {bundle['n_samples']:,})。データ: 株価 yfinance、財務 EDINET(提出日以降のみ使用)。金融業は除外、売買代金(20日中央値)3,000万円以上。</p>
</body></html>"""
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"ranking_{d.date()}.html"
    out.write_text(page, encoding="utf-8")
    (REPORTS / "latest.html").write_text(page, encoding="utf-8")
    if publish_dir:
        import os
        from pathlib import Path
        pd_ = Path(os.path.expandvars(os.path.expanduser(publish_dir)))
        try:
            pd_.mkdir(parents=True, exist_ok=True)
            (pd_ / "爆ハネランキング.html").write_text(page, encoding="utf-8")
        except Exception as e:
            log.warning(f"コピー先に書き込めません({pd_}): {e}")
    cols = ["p_jump", "p_crash", "score", "price", "mcap_oku", "PER", "PBR", "NCR", "DY", "RET1M", "MOM3", "HI52", "VOLSURGE", "VOL60", "MA25GAP", "value_oku"]
    t = today[cols].copy()
    t.insert(0, "name", [nm(c) for c in t.index])
    t.index.name = "code"
    t.to_csv(REPORTS / f"ranking_{d.date()}.csv", encoding="utf-8-sig")
    return str(out)
