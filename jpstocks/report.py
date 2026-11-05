"""毎日の「爆ハネ期待値ランキング」レポート(HTML / CSV)"""
from __future__ import annotations

import html
import json
import logging

import numpy as np
import pandas as pd

from .config import ROOT
from .jump import H
from .research import answer_check, final_picks, grade_cell, latest_grades, load_research, research_html

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


def _links(code) -> str:
    """銘柄コード(投資の森へのリンク) + Yahoo!ファイナンスのボタン"""
    return (f"<a href='https://nikkeiyosoku.com/stock/{code}/' target='_blank'>{code}</a>"
            f"<a class='yb' href='https://finance.yahoo.co.jp/quote/{code}.T' target='_blank' title='Yahoo!ファイナンス'>Y!</a>"
            f"<button class='fav' data-code='{code}' title='お気に入り'>☆</button>")


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
                "<b>5銘柄に絞るなら</b>、この並び順(割安度)より期待スコアの順のほうが検証で良かった(1年後 +12.5% 対 +7.7%)→ ページ上の「今日の最終候補」の「長期保有」。"
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
                    "<b>相場に引きずられて下がった(と推測される)優良株</b>: 黒字(直近の有報・半期報告書)・割安度が上位30%・最後の有報/半期報告書から20営業日以上・"
                    "直近1か月で市場全体以上に下落。並び順はランキングの点数(上位15銘柄)。"
                    "<br><b>注意</b>: 下げた理由(悪い材料があるか)は見ていません。決算短信・業績予想の修正・増資・不祥事などは使っているデータ(EDINETの有価証券報告書・半期報告書)に入っていないため、<b>個別の悪材料で下げた銘柄も混ざります</b>。条件を満たす銘柄全体では、検証(2019〜2026年)で3か月後に全銘柄平均より +1.7%(t=3.8、8年中7年プラス)。相場のお得度に関係なく効いていました(お得度が高い時は市場全体が上がりやすいだけ)。", dips))
    return out


def _simple_table(df: pd.DataFrame, nm, sec, budget: float) -> str:
    rows = []
    for k, (code, r) in enumerate(df.iterrows(), 1):
        cost100 = r["price"] * 100
        afford = "" if cost100 <= budget else ' <span class="warn">予算超</span>'
        rows.append(f"<tr><td>{k}</td><td>{_links(code)}</td>"
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


def _ev(g: pd.DataFrame, code) -> str:
    """Claude が3つのシナリオから計算した1〜2年後の期待値(割安カタリストの調査をした銘柄だけ)"""
    if code not in g.index or "ev_pct" not in g.columns or pd.isna(g.loc[code, "ev_pct"]):
        return "−"
    tip = html.escape(str(g.loc[code].get("scenarios", "")))
    return f"<span title='{tip}'>{float(g.loc[code, 'ev_pct']):+.0f}%</span>"


def _catalyst_table(df: pd.DataFrame, nm, sec, rank, grades: pd.DataFrame) -> str:
    rows = []
    for k, (code, r) in enumerate(df.iterrows(), 1):
        room = "−" if pd.isna(r.get("room_x")) else f"{r['room_x']*100:.0f}%"
        tags = "".join(f"<span class='g gB'>{html.escape(x)}</span> " for x in str(r["flags"]).split("・") if x)
        rows.append(f"<tr><td>{k}</td><td>{_links(code)}</td>"
                    f"<td class='name'>{html.escape(str(nm(code)))}<div class='sec'>{html.escape(str(sec(code)))}"
                    f"{' / 清原式' if r['kiyoshi'] else ' / 割安総合'}</div></td>"
                    f"<td class='num'>{r['price']:,.0f}</td><td class='num'>{r['mcap_oku']:,.0f}</td><td class='num'>{_fmt(r['PBR'],'{:.2f}')}</td>"
                    f"<td class='num'><b>{_fmt(r['NCR'],'{:.2f}')}</b></td><td class='num'>{room}</td><td class='why'>{tags}</td>"
                    f"<td class='num'>{r['score']*100:.0f}</td><td class='num'>{rank.get(code, '−')}</td>{grade_cell(grades, code)}"
                    f"<td class='num'>{_ev(grades, code)}</td></tr>")
    if not rows:
        return "<p class='note'>今日は該当する銘柄がありません。</p>"
    return ("<div class='wrap'><table><tr><th>#</th><th>コード</th><th>銘柄</th><th>株価</th><th>時価総額(億)</th><th>PBR</th>"
            "<th>ネットキャッシュ比率</th><th>営業利益÷過去5年の最高</th><th>当てはまる条件</th><th>期待スコア</th><th>ランキング順位</th>"
            "<th>Claude</th><th>Claudeの期待値(1〜2年)</th></tr>"
            + "".join(rows) + "</table></div>")


def _e(x) -> str:
    return html.escape(str(x))


def _sources(s) -> str:
    """調査の出典(URL を「;」区切り)を、サイト名の小さなリンクに"""
    from urllib.parse import urlparse
    out = []
    for u in str(s or "").replace("、", ";").split(";"):
        u = u.strip()
        if u.startswith("http"):
            host = urlparse(u).netloc.replace("www.", "")
            out.append(f"<a href='{_e(u)}' target='_blank' rel='noopener'>{_e(host)}</a>")
    return " ".join(out[:4])


def _pick_card(i: int, c: str, kind: str, pool: pd.DataFrame, today: pd.DataFrame, g: pd.DataFrame, nm, sec, rank: dict,
               market: dict | None, stop_loss: float, d: pd.Timestamp, other: list) -> str:
    """最終候補1銘柄のカード: なぜ選ばれたか(条件)・Claude の調査・数字・保有の目安"""
    from .research import GRADE_NAME
    r = today.loc[c]
    x = g.loc[c] if c in g.index else None
    sc = r["score"] * 100
    why = []
    if kind == "short":
        why.append(("ランキング", f"{rank.get(c, '−')}位(期待スコア {sc:.0f}点)"))
        mk = market.get("r20") if market else None
        mtxt = f"(市場全体 {mk*100:+.1f}%)" if mk is not None and pd.notna(mk) else ""
        why.append(("巻き添え安", f"直近1か月 {_fmt(r['RET1M'], '{:+.0f}')}%{mtxt}・黒字・割安度が上位30%"))
    else:
        why.append(("清原式", f"ネットキャッシュ比率 {_fmt(r['NCR'], '{:.2f}')}(1以上)・黒字"))
        why.append(("期待スコア", f"{sc:.0f}点(清原式 {len(pool)}銘柄の中で{list(pool.index).index(c) + 1}番目)"))
    if x is not None:
        dr = x.get("drop") if pd.notna(x.get("drop")) else "−"
        why.append(("Claude", f"{x['grade']}{'(A なので優先)' if x['grade'] == 'A' else ''}・下げた理由: {dr}"))
    else:
        why.append(("Claude", "まだ調査していません(平日の朝に調べます)"))
    if c in other:
        why.append(("重複", "もう一方の最終候補にも入っています"))
    why_html = "".join(f"<li><span>{_e(k)}</span>{_e(v)}</li>" for k, v in why)

    if x is not None:
        extra = ""
        for col, lab in [("catalyst", "カタリスト"), ("recovery", "業績回復"), ("scenarios", "シナリオ"), ("priced_in", "織り込み")]:
            if col in x.index and pd.notna(x.get(col)) and str(x.get(col)).strip():
                extra += f"<p class='cl-x'><b>{lab}</b> {_e(x[col])}</p>"
        if "ev_pct" in x.index and pd.notna(x.get("ev_pct")):
            extra += f"<p class='cl-x'><b>Claude の期待値(1〜2年)</b> {float(x['ev_pct']):+.0f}%</p>"
        src = _sources(x.get("sources"))
        claude = (f"<div class='cl-h'><span class='g g{x['grade']}'>{x['grade']}</span><b>{_e(GRADE_NAME.get(x['grade'], x['grade']))}</b>"
                  f"<span class='sub'>確信度 {_e(x['confidence'])} ・ {pd.Timestamp(x['date']):%m/%d} 調査</span></div>"
                  f"<p class='cl-s'>{_e(x['summary'])}</p>"
                  f"<ul class='pc'><li class='pro'><span>良い点</span>{_e(x['good'])}</li><li class='con'><span>注意点</span>{_e(x['risk'])}</li></ul>"
                  + extra + (f"<p class='src'>出典 {src}</p>" if src else ""))
    else:
        claude = "<div class='cl-h'><span class='g gB'>未</span><b>Claude の調査はまだです</b></div><p class='sub'>平日の朝に調べて、理由を付けます。</p>"

    def m(label, val, cls="", tip=""):
        t = f" title='{_e(tip)}'" if tip else ""
        return f"<div class='m'{t}><span>{label}</span><b class='{cls}'>{val}</b></div>"
    r1 = r["RET1M"]
    metrics = (m("株価", f"{r['price']:,.0f}<small>円</small>") + m("100株", f"{r['price']*100/1e4:,.1f}<small>万円</small>")
               + m("期待スコア", f"{sc:.0f}<small>点</small>", tip="3か月後の値上がりの順位の予測。平均50点、60点台なら上位")
               + m("直近1か月", f"{_fmt(r1, '{:+.0f}')}%", "up" if r1 > 0 else ("dn" if r1 < 0 else ""))
               + m("PER", _fmt(r["PER"]), tip="株価÷1株あたり利益。低いほど割安")
               + m("PBR", _fmt(r["PBR"], "{:.2f}"), tip="株価÷1株あたり純資産。1未満は解散価値より安い")
               + m("配当利回り", _fmt(r["DY"], "{:.1f}%"))
               + m("ネットキャッシュ比率", _fmt(r["NCR"], "{:.2f}"), tip="(流動資産+投資有価証券×70%−負債)÷時価総額。1以上なら実質の現金が時価総額より多い")
               + m("時価総額", f"{r['mcap_oku']:,.0f}<small>億円</small>")
               + m("52週高値比", _fmt(r["HI52"], "{:.0f}%"), tip="今の株価が過去1年の最高値の何%か")
               + m("爆ハネ確率", f"{r['p_jump']*100:.0f}%", tip="3か月以内に+30%以上になる確率の予測")
               + m("暴落確率", f"{r['p_crash']*100:.0f}%", tip="3か月以内に-30%以下になる確率の予測"))
    if kind == "short":
        plan = (f"<b>保有の目安</b> 翌営業日の寄り付きで買い、約3か月({_bday_after(d, H + 1):%Y-%m-%d}ごろ)まで。"
                f"損切り目安 {r['price']*(1+stop_loss):,.0f}円(任意)")
    else:
        plan = "<b>保有の目安</b> 1年以上。年に1〜2回、候補に残っているか見直す"
    return (f"<article class='pk'><div class='pk-a'><div class='pk-h'><span class='pk-n'>{i}</span><div class='pk-t'>"
            f"<div class='pk-name'>{_e(nm(c))}</div><div class='pk-sub'>{_links(c)}<span>{_e(sec(c))}</span></div></div></div>"
            f"<h4>選ばれた理由</h4><ul class='why2'>{why_html}</ul></div>"
            f"<div class='pk-b'>{claude}</div>"
            f"<div class='pk-c'><div class='mg'>{metrics}</div><p class='plan'>{plan}</p></div></article>")


def _hero(focus, long, today, g, nm, sec, rank, market, stop_loss, d, check_rank) -> str:
    """ページの最初: 今日の最終候補(3か月 / 長期)を、選ばれた理由と数字つきで"""
    from .research import LONG_NOTE, SHORT_NOTE, candidates_table, final_picks
    sp = [] if focus is None else final_picks(focus, g)
    lp = [] if long is None else final_picks(long, g)
    groups = [
        ("short", "3か月保有", sp, focus,
         [("対象", f"{len(today):,}銘柄"), ("ランキング60位以内 × 巻き添え安", f"{0 if focus is None else len(focus)}銘柄"),
          ("Claude の調査で C・悪材料を除外、A を優先", f"{len(sp)}銘柄")],
         [("3か月後、全銘柄平均との差", "+3.1%"), ("上がっていた割合", "65%"), ("−30%以下になった割合", "0.8%"), ("検証期間", "2019〜2026年(2026年は−2%)")],
         SHORT_NOTE, "今日は「ランキング60位以内 かつ 巻き添え安の条件」を満たす銘柄がありません。"),
        ("long", "長期保有(1年以上)", lp, long,
         [("対象", f"{len(today):,}銘柄"), ("清原式(ネットキャッシュ比率1以上・黒字)", f"{0 if long is None else len(long)}銘柄"),
          ("期待スコア順 + Claude の調査で C・悪材料を除外、A を優先", f"{len(lp)}銘柄")],
         [("1年後、全銘柄平均との差", "+12.5%"), ("2年後", "+38%"), ("上がっていた割合(1年)", "78%"), ("平均を上回った年", "7年中6年")],
         LONG_NOTE, "今日は清原式の条件を満たす銘柄がありません。"),
    ]
    sw = "".join(f"<button data-g='{k}'{' class=on' if j == 0 else ''}>{t}<span>{len(p)}</span></button>" for j, (k, t, p, *_rest) in enumerate(groups))
    secs = []
    for j, (k, t, picks, pool, funnel, stats, note, empty) in enumerate(groups):
        fn = "".join(f"<li><b>{_e(v)}</b><span>{_e(lab)}</span></li>" for lab, v in funnel)
        st = "".join(f"<div><b>{_e(v)}</b><span>{_e(lab)}</span></div>" for lab, v in stats)
        other = lp if k == "short" else sp
        cards = "".join(_pick_card(i, c, k, pool, today, g, nm, sec, rank, market, stop_loss, d, other) for i, c in enumerate(picks, 1)) \
            or f"<p class='empty'>{empty}</p>"
        cand = "" if pool is None or not len(pool) else (
            f"<details class='about'><summary>候補 {len(pool)} 銘柄の一覧(ここから最終候補を選んでいます)</summary>"
            + candidates_table(pool, g, nm, check_rank, picked=picks) + "</details>")
        secs.append(f"<section class='grp' data-g='{k}'{'' if j == 0 else ' hidden'}>"
                    f"<ol class='funnel'>{fn}</ol>{cards}"
                    f"<div class='bt'><h4>この選び方の過去の成績(Claude の評価を除いた部分)</h4><div class='stats'>{st}</div>"
                    f"<p class='note'>{note} Claude の評価(A/B/C)はまだ検証できていません(ページ下の答え合わせで確かめていきます)。</p></div>"
                    f"{cand}</section>")
    return (f"<section class='hero' id='picks'><div class='hero-h'><div><h2 class='h-big'>今日の最終候補</h2>"
            f"<p class='sub'>{d.date()} の終値で選んだ銘柄です。投資判断はご自身でお願いします。</p></div>"
            f"<div class='gsw' role='tablist'>{sw}</div></div>{''.join(secs)}</section>")


def write_report(today: pd.DataFrame, top: pd.DataFrame, dropped: list, w, bundle: dict, track: pd.DataFrame | None,
                 budget: float, stop_loss: float, publish_dir: str = "", market: dict | None = None,
                 dips: pd.DataFrame | None = None, focus: pd.DataFrame | None = None, long: pd.DataFrame | None = None,
                 cat: pd.DataFrame | None = None) -> str:
    d = pd.Timestamp(today["date"].iloc[0])
    names = w.universe.set_index(w.universe["code"].astype(str))
    def nm(c):
        return names["name"].get(c, "?") if c in names.index else "?"
    def sec(c):
        return names["sector33"].get(c, "") if c in names.index else ""

    research = load_research()
    grades = latest_grades(research, d)
    rows_html = []
    live = []   # 場中の株価更新(scripts/22_live_prices.py)に渡す: 銘柄とランクイン日の株価
    for k, (code, r) in enumerate(top.iterrows(), 1):
        new = r["days_in"] == 1
        status = '<span class="buy">買い時(新規ランクイン)</span>' if new else f'継続 {int(r["days_in"])}日目'
        cost100 = r["price"] * 100
        afford = "" if cost100 <= budget else ' <span class="warn">予算超(S株なら可)</span>'
        sell_day = _bday_after(r["entry_date"], H)
        # ランクイン日の終値は今の株価データから取り直す(その後に株式分割があっても比べられるように)
        ed = pd.Timestamp(r["entry_date"])
        entry_px = w.m.close.at[ed, code] if code in w.m.close.columns and ed in w.m.close.index else np.nan
        if pd.isna(entry_px):
            entry_px = r["entry_price"]
        since = r["price"] / entry_px - 1
        since_cls = "up" if since > 0 else ("dn" if since < 0 else "")
        stop = entry_px * (1 + stop_loss)
        live.append({"code": code, "rank": k, "name": str(nm(code)), "sector": str(sec(code)),
                     "entry_price": round(float(entry_px), 2), "price": round(float(r["price"]), 2)})
        cx = code in grades.index and (grades.loc[code, "grade"] == "C" or grades.loc[code].get("drop") == "個別の悪材料")
        rows_html.append(f"""<tr class="{'new' if new else ''}{' cx' if cx else ''}" data-code="{code}" data-entry="{entry_px}">
<td>{k}</td><td>{_links(code)}</td>
<td class="name">{html.escape(str(nm(code)))}<div class="sec">{html.escape(str(sec(code)))}</div></td>
{grade_cell(grades, code)}
<td class="num"><b>{r['score']*100:.0f}</b><span class="bar" style="width:{max(2, min(40, (r['score']*100-45)*2)):.0f}px"></span></td>
<td class="num">{r['p_jump']*100:.0f}%</td><td class="num">{r['p_crash']*100:.0f}%</td>
<td>{status}</td>
<td class="num px">{r['price']:,.0f}</td><td class="num">{cost100/1e4:,.1f}万{afford}</td>
<td>{ed.date()}<div class="sec">@{entry_px:,.0f}円</div></td>
<td class="num since {since_cls}"><b>{since*100:+.1f}%</b><div class="sec">{r['price']-entry_px:+,.0f}円</div></td>
<td>{sell_day.date()}</td><td class="num">{stop:,.0f}</td>
<td class="num">{_fmt(r['PER'])}</td><td class="num">{_fmt(r['PBR'],'{:.2f}')}</td><td class="num">{_fmt(r['DY'],'{:.1f}%')}</td><td class="num">{_fmt(r['NCR'],'{:.2f}')}</td>
<td class="num">{r['mcap_oku']:,.0f}</td><td class="num">{_fmt(r['RET1M'],'{:+.0f}')}%</td><td class="num">{_fmt(r['HI52'],'{:.0f}')}%</td>
<td class="num">{_fmt(r['VOLSURGE'],'{:.1f}')}倍</td><td class="num">{_fmt(r['VOL60'],'{:.0f}')}%</td>
</tr>""")

    # 保有銘柄
    pos = load_positions()
    # 相場の状態(お得度)と、相場に引きずられて下がった優良株
    mk_html, mk_card = "", ""
    if market is not None:
        colors = {"大チャンス": "#b42318", "買い場": "#d9480f", "押し目": "#e8a200", "やや割安": "#5c8a6b", "平常": "#8a8a85"}
        c = colors.get(market["level"], "#888")
        strip = "".join(f"<span title='{dd.date()} {lv} {v:.0f}' style='background:{colors[lv]}'></span>" for dd, v, lv in market["history"])
        ind_rows = "".join(f"<tr><td>{html.escape(k)}</td><td class='num'>{v:,.1f}</td><td class='num'>{p:.0f}</td></tr>" for k, v, p in market["indicators"])
        legend = " ".join(f"<span style='color:{colors[n]}'>■</span>{n}" for n in ["大チャンス", "買い場", "押し目", "やや割安", "平常"])
        mk_html = (f"<details class='in'><summary>計算のしかたと指標の内訳</summary><p class='note'>"
                   f"9つの売られすぎ指標(騰落レシオ・25日線より上の銘柄の割合・52週安値の銘柄数・下落の深さ・値動きの大きさなど)を、過去と比べた位置で採点。"
                   f"95以上=大チャンス / 85以上=買い場 / 70以上=押し目 / 50以上=やや割安。<br>{legend}</p>"
                   "<div class='wrap'><table><tr><th>指標</th><th>今の値</th><th>お得度への寄与(0〜100)</th></tr>"
                   + ind_rows + "</table></div></details>")
        mk_card = (f"<div class='card mk'><h3>相場のお得度(市場全体の売られすぎ度)</h3><div class='big' style='color:{c}'>{market['level']} "
                   f"<span class='sub' style='font-size:14px;font-weight:400'>{market['score']:.0f} / 100</span></div>"
                   f"<div class='gauge'><i style='left:{min(99.5, max(0.5, market['score'])):.1f}%'></i></div>"
                   "<div class='gauge-l'><span>平常</span><span>50 やや割安</span><span>70 押し目</span><span>85 買い場</span><span>95</span></div>"
                   f"<p class='sub' style='margin:8px 0 4px'>{html.escape(market['note'])}</p>"
                   f"<div class='sub'>直近20営業日 <span class='strip'>{strip}</span></div>{mk_html}</div>")
        mk_html = ""

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
            prow.append(f"<tr><td>{_links(c)}</td><td>{html.escape(str(nm(c)))}</td><td>{pd.Timestamp(p['buy_date']).date()}</td>"
                        f"<td class='num'>{p['buy_price']:,.0f}</td><td class='num'>{cur:,.0f}</td><td class='num'>{pl*100:+.1f}%</td>"
                        f"<td>{due.date()}</td><td class='num'>{p['buy_price']*(1+stop_loss):,.0f}</td>"
                        f"<td class='num'>{rank or '圏外'}</td><td>{act}</td></tr>")
        pos_html = f"""<h2>保有中の銘柄(config/my_positions.csv)</h2>
<div class="wrap"><table><tr><th>コード</th><th>銘柄</th><th>買った日</th><th>買値</th><th>現在値</th><th>損益</th><th>3か月後(売り時)</th><th>損切り目安</th><th>今日の順位</th><th>判定</th></tr>
{''.join(prow)}</table></div>"""

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
    rank = {c: k for k, c in enumerate(today.index, 1)}
    res_html = research_html(top, grades, answer_check(research, w, H), nm, focus, rank_of=rank.get, long=long, with_picks=False)
    def cl(df):
        return [] if df is None else [{"code": c, "rank": rank[c], "name": str(nm(c)), "sector": str(sec(c)), "price": round(float(r["price"]), 2),
                                       "ret1m_pct": round(float(r["RET1M"]), 1)} for c, r in df.iterrows()]
    cands, long_cands = cl(focus), cl(None if long is None else long.head(15))
    cat_cands = [] if cat is None else [{**x, "flags": str(cat.loc[x["code"], "flags"]), "kiyohara": bool(cat.loc[x["code"], "kiyoshi"])}
                                        for x in cl(cat.head(15))]
    tab_btn = f"<button class='tab' data-t='bakuhane'>ランキング(上位{len(top)})</button>" + "".join(
        f"<button class='tab' data-t='{tid}'>{html.escape(name)}</button>" for tid, name, _, _ in alts) + \
        ("" if cat is None else f"<button class='tab' data-t='catalyst'>割安カタリスト({len(cat)})</button>") + \
        "<button class='tab' data-t='mypage'>マイページ</button>"
    from .mypage import mypage_parts, stocks_json
    mp_html, mp_js = mypage_parts(H, stop_loss)
    alt_html = "".join(f"<section class='pane' id='tab-{tid}'><p class='note'>{desc}</p>{_simple_table(df, nm, sec, budget)}</section>"
                       for tid, name, desc, df in alts)
    if cat is not None:
        from .catalyst import CATALYST_NOTE
        alt_html += f"<section class='pane' id='tab-catalyst'><p class='note'>{CATALYST_NOTE}</p>{_catalyst_table(cat, nm, sec, rank, grades)}</section>"

    hero = _hero(focus, long, today, grades, nm, sec, rank, market, stop_loss, d, rank.get)
    from .ui import HEAD, SCRIPT, STYLE, THEME_BTN

    base_j, base_c = bundle["base_jump"] * 100, bundle["base_crash"] * 100
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>爆ハネ期待値ランキング {d.date()}</title>
{HEAD}<style>{STYLE}</style></head><body>
<header class="top"><div class="top-in"><div class="brand"><div class="logo">爆</div><h1><span>爆ハネ</span>期待値ランキング</h1></div>
<span class="chip"><i class="dot"></i>{d.date()} 終値</span>
<span class="chip upd">更新 {pd.Timestamp.now().strftime('%m/%d %H:%M')}(平日16時ごろ)</span>
<a class="hbtn" href="#lists" data-go="mypage" data-anchor="lists">マイページ</a>{THEME_BTN}</div></header>
<main>
{hero}
<div class="cards">{mk_card}<div class="card guide"><h3>このページの使い方</h3><ol class="steps">
<li><b>最終候補</b>のカードで、選ばれた理由・Claude の調査・数字を確認します。「3か月保有」と「長期保有」は上のボタンで切り替え。</li>
<li>銘柄コードを押すと詳しい予想、<b>Y!</b> で Yahoo!ファイナンスのチャート、<b>☆</b> でお気に入り(マイページでログインが必要)。</li>
<li>買ったら<b>マイページ</b>に登録すると、売り時(3か月後)と損切りラインを毎日表示します。</li>
<li>下の「ランキングと参考リスト」は、最終候補の元になったランキングと、ほかの選び方のリストです(参考)。</li></ol></div></div>
{pos_html}
<section class="lists" id="lists"><h2>ランキングと参考リスト</h2>
<p class="note">最終候補とは別の、参考の情報です。表の見出しを押すと並べ替え、検索欄や「Claude A」などのボタンで絞り込みができます。</p>
<nav class="tabs sub">{tab_btn}</nav>
<section class="pane" id="tab-bakuhane">
<p class="note"><b>ランキング(上位{len(top)}銘柄)</b>: 期待スコアの高い順。「Claude」の列は直近の定性評価(A=買い材料あり / B=中立 / C=避けたい。押すと理由)。C と「個別の悪材料」の行は薄く表示。</p>
<p class="note" id="live-note" hidden></p>
<div class="wrap"><table>
<tr><th>#</th><th>コード</th><th>銘柄</th><th>Claude</th><th>期待スコア</th><th>爆ハネ確率</th><th>暴落確率</th><th>買い時</th><th>株価</th><th>100株</th><th>ランクイン</th><th>ランクイン後</th><th>売り時の目安</th><th>損切り目安</th>
<th>PER</th><th>PBR</th><th>配当利回り</th><th>ネットキャッシュ比率</th><th>時価総額(億)</th><th>1か月</th><th>52週高値比</th><th>出来高(直近/平常)</th><th>年ボラ</th></tr>
{''.join(rows_html)}
</table></div>
{drop_html}
{track_html}
</section>
{alt_html}
{mp_html}
</section>
<section class="claude"><h2>Claude の調査と答え合わせ</h2>{res_html}
<details class="about"><summary>期待スコア(ランキング)の見方と、検証の結果</summary><p class="note">並び順 = <b>期待スコア</b>: 3か月後の株価の上がり方が、全対象銘柄の中で何番目くらいになるかの予測(100点満点、平均50点。60点台でも上位の予測です)。
株価の動き・出来高・割安度・業績の伸びなど30項目から計算。参考として 3か月以内に+30%以上(爆ハネ)/-30%以下(暴落)になる確率も表示(全銘柄の平均は {base_j:.0f}% / {base_c:.0f}%)。<br>
<b>検証</b>(2019〜2026年、毎年それ以前のデータだけで学習): 毎日の上位5銘柄は3か月後に全銘柄平均より <b>+2.6%</b>、上がっていた割合 <b>58%</b>、-30%以下まで下げたのは3%。
上位50位までは平均より +1〜1.5%。差は統計的にはやや弱い(t値1〜2.6)ので、最終候補では巻き添え安の条件と Claude の評価を組み合わせて絞り込んでいます。損切り目安({stop_loss*100:.0f}%)は任意。投資判断はご自身で。</p></details>
</section>
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
// 場中の株価(live.json)があれば、株価と「ランクイン後」だけ差し替える。順位は {d.date()} 終値のまま
(async function(){{
  var L; try{{ L = await (await fetch('live.json', {{cache:'no-store'}})).json(); }}catch(e){{ return; }}
  if(!L || !L.prices || !L.asof || L.asof.slice(0,10) <= '{d.date()}') return;
  var fmt = function(x){{ return Math.round(x).toLocaleString('ja-JP'); }}, n = 0;
  document.querySelectorAll('#tab-bakuhane tr[data-code]').forEach(function(tr){{
    var p = L.prices[tr.dataset.code], e = parseFloat(tr.dataset.entry);
    if(p == null || !(e > 0)) return;
    var s = p / e - 1, td = tr.querySelector('td.since');
    tr.querySelector('td.px').textContent = fmt(p);
    td.classList.toggle('up', s > 0); td.classList.toggle('dn', s < 0);
    td.innerHTML = '<b>' + (s >= 0 ? '+' : '') + (s * 100).toFixed(1) + '%</b><div class="sec">' + (p >= e ? '+' : '-') + fmt(Math.abs(p - e)) + '円</div>';
    n++;
  }});
  var note = document.getElementById('live-note');
  note.innerHTML = '<b>株価・ランクイン後は ' + L.asof.slice(5,10).replace('-','/') + ' ' + L.asof.slice(11,16) + ' 時点</b>(場中・約20分遅れ、' + n + '銘柄)。順位と確率は {d.date()} の終値で計算したもの。';
  note.hidden = false;
}})();
</script>
{mp_js}
<p class="note">モデル: {bundle['trained_until']} までのデータで学習(サンプル {bundle['n_samples']:,})。データ: 株価 yfinance、財務 EDINET(提出日以降のみ使用)。金融業は除外、売買代金(20日中央値)3,000万円以上。</p>
</main>
{SCRIPT}
</body></html>"""
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"ranking_{d.date()}.html"
    out.write_text(page, encoding="utf-8")
    (REPORTS / "latest.html").write_text(page, encoding="utf-8")
    (REPORTS / "stocks.json").write_text(stocks_json(today, w, market), encoding="utf-8")
    (REPORTS / "top.json").write_text(json.dumps({"date": str(d.date()), "stocks": live, "candidates": cands, "long_candidates": long_cands,
                                                   "picks_short": [] if focus is None else final_picks(focus, grades),
                                                   "picks_long": [] if long is None else final_picks(long, grades),
                                                   "catalyst_candidates": cat_cands}, ensure_ascii=False), encoding="utf-8")
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
