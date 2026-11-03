"""Claude による定性調査(業界動向・決算・材料)の結果を読み、ランキングと組み合わせる

research/qualitative.csv: 週1回、このPCの Claude Code(スケジュール実行)がランキング上位を調べて追記する
(手順: research/weekly_prompt.md、追記: scripts/23_add_research.py)。
評価 A=3か月で市場平均を上回る材料がある / B=特に材料なし(中立) / C=避けたい材料がある
"""
from __future__ import annotations

import html

import numpy as np
import pandas as pd

from .config import ROOT

RESEARCH = ROOT / "research" / "qualitative.csv"
COLUMNS = ["date", "code", "name", "rank", "price", "grade", "confidence", "summary", "good", "risk", "sources"]
FRESH_DAYS = 35          # この日数より古い調査は「今の評価」として使わない
GRADE_NAME = {"A": "A 買い材料あり", "B": "B 中立", "C": "C 避けたい"}


def load_research() -> pd.DataFrame | None:
    if not RESEARCH.exists():
        return None
    r = pd.read_csv(RESEARCH, dtype={"code": str}, parse_dates=["date"])
    r = r[r["grade"].isin(["A", "B", "C"])]
    return r if len(r) else None


def latest_grades(r: pd.DataFrame | None, asof: pd.Timestamp) -> pd.DataFrame:
    """銘柄ごとの最新の評価(FRESH_DAYS 以内のもの)"""
    if r is None:
        return pd.DataFrame(columns=COLUMNS).set_index("code")
    r = r[(r["date"] <= asof + pd.Timedelta(days=7)) & (r["date"] >= asof - pd.Timedelta(days=FRESH_DAYS))]
    return r.sort_values("date").groupby("code").tail(1).set_index("code")


def answer_check(r: pd.DataFrame | None, w, H: int) -> pd.DataFrame | None:
    """調査日の終値から H 営業日後の終値までのリターンと、同じ期間の全対象銘柄の平均(答え合わせ)"""
    if r is None:
        return None
    px = w.m.adj_close
    dates = px.index
    rows = []
    for _, x in r.iterrows():
        k = dates.searchsorted(x["date"], side="right") - 1      # 調査日(週末なら直前の営業日)の終値
        if k < 0 or x["code"] not in px.columns:
            continue
        done = k + H < len(dates)
        j = k + H if done else len(dates) - 1
        ret = px[x["code"]].iat[j] / px[x["code"]].iat[k] - 1
        d0 = dates[k]
        e = w.elig.loc[d0] if d0 in w.elig.index else None
        bench = (px.iloc[j][e[e].index] / px.iloc[k][e[e].index] - 1).mean() if e is not None else np.nan
        rows.append({"date": x["date"], "code": x["code"], "grade": x["grade"], "ret": ret, "bench": bench, "done": done})
    return pd.DataFrame(rows) if rows else None


def grade_cell(g: pd.DataFrame, code: str) -> str:
    if code not in g.index:
        return "<td class='gr'>−</td>"
    x = g.loc[code]
    tip = html.escape(f"{x['date']:%m/%d} 調査 / 確信度 {x['confidence']}\n{x['summary']}")
    return f"<td class='gr'><span class='g g{x['grade']}' title='{tip}'>{x['grade']}</span></td>"


def research_html(top: pd.DataFrame, g: pd.DataFrame, check: pd.DataFrame | None, nm) -> str:
    """絞り込み候補(ランキング上位 × Claude評価) + 調査の詳細 + 答え合わせ"""
    out = []
    inr = [c for c in top.index if c in g.index]
    picks = [c for c in inr if g.loc[c, "grade"] == "A"]
    out.append("<h2>絞り込み候補(ランキング × Claudeの定性評価)</h2>")
    if not inr:
        out.append("<p class='note'>まだ定性調査の結果がありません。週1回、ランキング上位10銘柄ほどを Claude が調べて A/B/C を付けます。</p>")
        return "".join(out)
    if picks:
        items = "".join(f"<li><b>{list(top.index).index(c)+1}位 {c} {html.escape(str(nm(c)))}</b> "
                        f"<span class='g gA'>A</span> 確信度 {html.escape(str(g.loc[c, 'confidence']))} — {html.escape(str(g.loc[c, 'summary']))}</li>"
                        for c in picks)
        out.append(f"<ul class='picks'>{items}</ul>")
    else:
        out.append("<p class='note'>今のランキングに A 評価の銘柄はありません(B の上位から選ぶか、次の調査を待つ)。</p>")
    out.append("<p class='note'>組み合わせ方: ランキング上位のうち <b>A を優先、C は外す</b>。B は順位どおり。"
               "評価は Claude がWeb上の決算・ニュース・業界動向を読んで付けたもので、検証済みの数字ではありません。下の答え合わせで効き目を確かめていきます。投資判断はご自身で。</p>")
    rows = []
    for c in inr:
        x = g.loc[c]
        rows.append(f"<tr><td>{list(top.index).index(c)+1}</td><td>{c}</td><td class='name'>{html.escape(str(nm(c)))}</td>"
                    f"<td><span class='g g{x['grade']}'>{x['grade']}</span></td><td>{html.escape(str(x['confidence']))}</td>"
                    f"<td>{x['date']:%m/%d}</td><td class='why'>{html.escape(str(x['summary']))}"
                    f"<div class='sec'>＋ {html.escape(str(x['good']))}<br>− {html.escape(str(x['risk']))}</div></td></tr>")
    out.append("<details><summary class='note'>調査の詳細(クリックで開く)</summary><div class='wrap'><table>"
               "<tr><th>順位</th><th>コード</th><th>銘柄</th><th>評価</th><th>確信度</th><th>調査日</th><th>理由</th></tr>"
               + "".join(rows) + "</table></div></details>")
    if check is not None and len(check):
        t = check.dropna(subset=["ret"])
        res = []
        for gr in ["A", "B", "C"]:
            for done, lab in [(True, "3か月後(確定)"), (False, "途中経過")]:
                s = t[(t["grade"] == gr) & (t["done"] == done)]
                if len(s):
                    ex = s["ret"] - s["bench"]
                    res.append(f"<tr><td><span class='g g{gr}'>{gr}</span></td><td>{lab}</td><td class='num'>{len(s)}</td>"
                               f"<td class='num'>{s['ret'].mean()*100:+.1f}%</td><td class='num'>{ex.mean()*100:+.1f}%</td>"
                               f"<td class='num'>{(s['ret'] > 0).mean()*100:.0f}%</td></tr>")
        out.append("<h2>Claude評価の答え合わせ</h2><p class='note'>調査日の終値から3か月(63営業日)後までの株価の変化。"
                   "A が B・C より良ければ、定性評価が役に立っているということ。件数が少ないうちは偶然の差が大きいので、20件以上たまるまでは参考程度に。</p>"
                   "<table><tr><th>評価</th><th>期間</th><th>件数</th><th>平均</th><th>全銘柄平均との差</th><th>上がった割合</th></tr>"
                   + "".join(res) + "</table>")
    return "".join(out)
