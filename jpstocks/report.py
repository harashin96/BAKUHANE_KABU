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
    return "−" if pd.isna(x) else f.format(x)


def alt_rankings(today: pd.DataFrame, dips: pd.DataFrame | None = None) -> list:
    """切り替えて見る別のランキング: (id, タブ名, 説明, 表)"""
    t = today.copy()
    prof = t["PER"] > 0
    out = []
    k = t[(t["NCR"] >= 1) & prof].sort_values("kiyo", ascending=False).head(60)
    out.append(("kiyohara", f"清原式({len(k)})",
                "<b>清原基準</b>: ネットキャッシュ比率(流動資産+投資有価証券×70%−負債)÷時価総額 が<b>1以上</b>の黒字企業。並び順は「ネットキャッシュ比率と低PERの順位」の平均。"
                "検証(2017〜2025年): 該当銘柄を全部均等に持つと市場平均より<b>年+10%</b>(t=3.9)、直近1年も+8%。"
                "1〜3銘柄に絞ると成績は運しだいになるので、<b>できるだけ多くの銘柄に分けて</b>(S株なら少額で可)、3か月〜半年ごとに見直すのが検証どおりの使い方。"
                "<br>注意: 不動産・建設などは流動資産に「販売用不動産」「未成工事支出金」が多く含まれ、現金ではないのに比率が高く出やすい(実際より割安に見える)。", k))
    v = t[prof].copy()
    for c, asc in [("NCR", True), ("PER", False), ("PBR", False), ("DY", True)]:
        v["r_" + c] = v[c].rank(pct=True, ascending=asc)
    v["vscore"] = v[["r_NCR", "r_PER", "r_PBR", "r_DY"]].mean(axis=1)
    v = v.sort_values("vscore", ascending=False).head(30)
    out.append(("value", "割安総合",
                "<b>割安総合</b>: ネットキャッシュ比率・低PER・低PBR・高配当の4つの順位の平均(黒字企業のみ)。"
                "検証(2017〜2025年): 上位30銘柄で市場平均より<b>年+8%</b>(t=2.7、9年中8年で勝ち)。直近1年は+2.5%。月1回〜四半期ごとに入れ替え。", v))
    dy = t[prof & (t["DY"] > 0) & (t["DY"] < 15)].sort_values("DY", ascending=False).head(30)
    out.append(("dividend", "高配当",
                "<b>高配当</b>: 予想ではなく直近の有価証券報告書の配当総額÷時価総額(黒字企業のみ)。"
                "検証では市場平均より年+2〜4%程度と効果は弱め(t≈1)。配当を受け取りたい人向けの参考。", dy))
    if dips is not None:
        out.append(("dip", f"巻き添え安({len(dips)})",
                    "<b>相場に引きずられて下がった優良株</b>: 黒字・割安度が上位30%・決算発表から20営業日以上(業績悪化による下げではない)・"
                    "直近1か月で市場全体以上に下落。並び順はランキングの点数。<b>相場のお得度が「押し目」以上のとき</b>に買う候補(平常時の上乗せは小さい)。", dips))
    return out


def _simple_table(df: pd.DataFrame, nm, sec, budget: float) -> str:
    rows = []
    for k, (code, r) in enumerate(df.iterrows(), 1):
        cost100 = r["price"] * 100
        afford = "" if cost100 <= budget else ' <span class="warn">予算超</span>'
        rows.append(f"<tr><td>{k}</td><td><a href='https://kabutan.jp/stock/?code={code}' target='_blank'>{code}</a></td>"
                    f"<td class='name'>{html.escape(str(nm(code)))}<div class='sec'>{html.escape(str(sec(code)))}</div></td>"
                    f"<td class='num'>{r['p_jump']*100:.0f}%</td><td class='num'>{r['p_crash']*100:.0f}%</td>"
                    f"<td class='num'>{r['price']:,.0f}</td><td class='num'>{cost100/1e4:,.1f}万{afford}</td>"
                    f"<td class='num'>{_fmt(r['PER'])}</td><td class='num'>{_fmt(r['PBR'],'{:.2f}')}</td>"
                    f"<td class='num'><b>{_fmt(r['NCR'],'{:.2f}')}</b></td><td class='num'>{_fmt(r['DY'],'{:.1f}%')}</td>"
                    f"<td class='num'>{r['mcap_oku']:,.0f}</td><td class='num'>{_fmt(r['RET1M'],'{:+.0f}')}%</td><td class='num'>{_fmt(r['HI52'],'{:.0f}')}%</td></tr>")
    if not rows:
        return "<p class='note'>今日は該当する銘柄がありません。</p>"
    return ("<div class='wrap'><table><tr><th>#</th><th>コード</th><th>銘柄</th><th>爆ハネ確率</th><th>暴落確率</th><th>株価</th><th>100株</th>"
            "<th>PER</th><th>PBR</th><th>ネットキャッシュ比率</th><th>配当利回り</th><th>時価総額(億)</th><th>1か月</th><th>52週高値比</th></tr>"
            + "".join(rows) + "</table></div>")


def write_report(today: pd.DataFrame, top: pd.DataFrame, dropped: list, w, bundle: dict, track: pd.DataFrame | None,
                 budget: float, stop_loss: float, publish_dir: str = "", market: dict | None = None,
                 dips: pd.DataFrame | None = None) -> str:
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
<td class="num">{_fmt(r['PER'])}</td><td class="num">{_fmt(r['PBR'],'{:.2f}')}</td><td class="num">{_fmt(r['DY'],'{:.1f}%')}</td><td class="num">{_fmt(r['NCR'],'{:.2f}')}</td>
<td class="num">{r['mcap_oku']:,.0f}</td><td class="num">{_fmt(r['RET1M'],'{:+.0f}')}%</td><td class="num">{_fmt(r['HI52'],'{:.0f}')}%</td>
<td class="num">{_fmt(r['VOLSURGE'],'{:.1f}')}倍</td><td class="num">{_fmt(r['VOL60'],'{:.0f}')}%</td>
</tr>""")

    # 保有銘柄
    pos = load_positions()
    # 相場の状態(お得度)と、相場に引きずられて下がった優良株
    mk_html = ""
    if market is not None:
        colors = {"大チャンス": "#b42318", "買い場": "#d9480f", "押し目": "#e8a200", "やや割安": "#5c8a6b", "平常": "#8a8a85"}
        c = colors.get(market["level"], "#888")
        strip = "".join(f"<span title='{dd.date()} {lv} {v:.0f}' style='display:inline-block;width:14px;height:14px;margin-right:2px;border-radius:3px;background:{colors[lv]}'></span>"
                        for dd, v, lv in market["history"])
        ind_rows = "".join(f"<tr><td>{html.escape(k)}</td><td class='num'>{v:,.1f}</td><td class='num'>{p:.0f}</td></tr>" for k, v, p in market["indicators"])
        legend = " ".join(f"<span style='color:{colors[n]}'>■</span>{n}" for n in ["大チャンス", "買い場", "押し目", "やや割安", "平常"])
        mk_html = (f"<h2>相場のお得度: <span style='color:{c}'>{market['level']}</span> "
                   f"<span style='color:var(--mut);font-weight:400'>({market['score']:.0f} / 100)</span></h2>"
                   f"<p class='note'>{html.escape(market['note'])}<br>"
                   f"直近20営業日: {strip} <span style='font-size:11px'>{legend}</span><br>"
                   f"9つの売られすぎ指標(騰落レシオ・25日線より上の銘柄の割合・52週安値の銘柄数・下落の深さ・値動きの大きさなど)を、過去と比べた位置で採点。"
                   f"95以上=大チャンス / 85以上=買い場 / 70以上=押し目 / 50以上=やや割安。</p>"
                   "<details><summary class='note'>指標の内訳</summary><table><tr><th>指標</th><th>今の値</th><th>お得度への寄与(0〜100)</th></tr>"
                   + ind_rows + "</table></details>")
        if dips is not None and len(dips):
            drow = []
            for code, r in dips.iterrows():
                drow.append(f"<tr><td><a href='https://kabutan.jp/stock/?code={code}' target='_blank'>{code}</a></td>"
                            f"<td class='name'>{html.escape(str(nm(code)))}<div class='sec'>{html.escape(str(sec(code)))}</div></td>"
                            f"<td class='num'>{r['RET1M']:+.0f}%</td><td class='num'>{r['p_jump']*100:.0f}%</td><td class='num'>{r['p_crash']*100:.0f}%</td>"
                            f"<td class='num'>{r['price']:,.0f}</td><td class='num'>{_fmt(r['PER'])}</td><td class='num'>{_fmt(r['PBR'],'{:.2f}')}</td>"
                            f"<td class='num'>{_fmt(r['DY'],'{:.1f}%')}</td><td class='num'>{_fmt(r['NCR'],'{:.2f}')}</td><td class='num'>{int(r['AGE'])}</td></tr>")
            body = (f"<p class='note'><b>相場に引きずられて下がった優良株</b>(黒字・割安度が上位30%・決算発表から20営業日以上=業績の悪化による下げではない・"
                    f"直近1か月で市場全体({market['r20']*100:+.1f}%)以上に下落)。並び順はランキングの点数。"
                    "お得度が「押し目」以上のときに、ランキング上位とあわせて買う候補。</p>"
                    "<div class='wrap'><table><tr><th>コード</th><th>銘柄</th><th>1か月</th><th>爆ハネ確率</th><th>暴落確率</th><th>株価</th><th>PER</th><th>PBR</th><th>配当利回り</th><th>ネットキャッシュ比率</th><th>決算から(営業日)</th></tr>"
                    + "".join(drow) + "</table></div>")
            if market["level"] in ("大チャンス", "買い場", "押し目"):
                mk_html += body
            else:
                mk_html += "<details><summary class='note'>相場に引きずられて下がった優良株(今は参考。クリックで開く)</summary>" + body + "</details>"

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

    alts = alt_rankings(today, dips)
    tab_btn = "<button class='tab' data-t='bakuhane'>爆ハネ期待値</button>" + "".join(
        f"<button class='tab' data-t='{tid}'>{html.escape(name)}</button>" for tid, name, _, _ in alts)
    alt_html = "".join(f"<section class='pane' id='tab-{tid}'><p class='note'>{desc}</p>{_simple_table(df, nm, sec, budget)}</section>"
                       for tid, name, desc, df in alts)

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
.tabs{{display:flex;flex-wrap:wrap;gap:6px;margin:20px 0 4px;position:sticky;top:0;background:var(--bg);padding:6px 0;z-index:2}}
.tab{{font:inherit;font-size:13px;padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:transparent;color:var(--fg);cursor:pointer}}
.tab.on{{background:var(--acc);border-color:var(--acc);color:#fff}} .pane{{display:none}} .pane.on{{display:block}}
</style></head><body>
<h1>爆ハネ期待値ランキング <span style="color:var(--mut);font-weight:400">{d.date()} 終値時点</span></h1>
<p class="note">作成: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}(平日18:30ごろ自動更新)</p>
<p class="note">並び順 = 「3か月以内に+30%以上(爆ハネ)の確率」−「3か月以内に-30%以下(暴落)の確率」。全銘柄の平均は 爆ハネ {base_j:.0f}% / 暴落 {base_c:.0f}%。<br>
<b>使い方</b>: 「買い時(新規ランクイン)」の銘柄を翌営業日の寄り付きで買い、<b>約3か月(63営業日)保有</b>が検証で最も良かった方法です。
損切り目安({stop_loss*100:.0f}%)は任意: 平均リターンは少し下がるが、大きな損を防ぐ。
過去の検証(2019〜2025年)では上位20銘柄の3か月リターンが全銘柄平均より約+2.8%高かった一方、1銘柄ずつでは中央値は+1%程度で、3〜4銘柄に1つが大きく跳ねる分布です。<b>数銘柄に分けて買う</b>ことを前提にしてください。投資判断はご自身で。</p>
{mk_html}
{pos_html}
<div class="tabs">{tab_btn}</div>
<section class="pane" id="tab-bakuhane">
<p class="note"><b>爆ハネ期待値</b>: 3か月以内に+30%以上の確率 − -30%以下の確率 の高い順(上位{len(top)}銘柄)。「買い時(新規ランクイン)」の翌営業日に買い、約3か月保有。</p>
<div class="wrap"><table>
<tr><th>#</th><th>コード</th><th>銘柄</th><th>爆ハネ確率</th><th>暴落確率</th><th>買い時</th><th>株価</th><th>100株</th><th>ランクイン</th><th>売り時の目安</th><th>損切り目安</th>
<th>PER</th><th>PBR</th><th>配当利回り</th><th>ネットキャッシュ比率</th><th>時価総額(億)</th><th>1か月</th><th>52週高値比</th><th>出来高(直近/平常)</th><th>年ボラ</th></tr>
{''.join(rows_html)}
</table></div>
{drop_html}
{track_html}
</section>
{alt_html}
<script>
(function(){{
  var tabs=document.querySelectorAll('.tab'), panes=document.querySelectorAll('.pane');
  function show(id){{
    var ok=false; panes.forEach(function(p){{var on=p.id==='tab-'+id; p.classList.toggle('on',on); ok=ok||on;}});
    if(!ok){{id='bakuhane'; document.getElementById('tab-bakuhane').classList.add('on');}}
    tabs.forEach(function(b){{b.classList.toggle('on',b.dataset.t===id);}});
    try{{localStorage.setItem('tab',id);}}catch(e){{}}
  }}
  tabs.forEach(function(b){{b.addEventListener('click',function(){{show(b.dataset.t); history.replaceState(null,'','#'+b.dataset.t);}});}});
  var first=(location.hash||'').slice(1); if(!first){{try{{first=localStorage.getItem('tab')||'';}}catch(e){{}}}}
  show(first||'bakuhane');
}})();
</script>
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
