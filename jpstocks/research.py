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
COLUMNS = ["date", "code", "name", "rank", "price", "grade", "confidence", "drop", "summary", "good", "risk", "sources",
           # 割安カタリストの候補だけ(2026-11 に追加。それより前の行は空欄)
           "catalyst", "recovery", "scenarios", "ev_pct", "priced_in"]
DROP = ["巻き込まれ", "個別の悪材料", "理由不明", "下げていない"]   # 直近の下げの理由
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


def _f(x, f="{:.1f}"):
    return "−" if pd.isna(x) else f.format(x)


def grade_cell(g: pd.DataFrame, code: str) -> str:
    if code not in g.index:
        return "<td class='gr'>−</td>"
    x = g.loc[code]
    tip = html.escape(f"{x['date']:%m/%d} 調査 / 確信度 {x['confidence']}\n{x['summary']}")
    return f"<td class='gr'><span class='g g{x['grade']}' title='{tip}'>{x['grade']}</span></td>"


def final_picks(focus: pd.DataFrame, g: pd.DataFrame, n: int = 5) -> list:
    """候補から最終候補を選ぶ: C と「個別の悪材料」は外し、A を先に、残りは候補の並び順(期待スコア順)。
    候補に tier 列(長期: 会社予想が増益なら0)があれば、tier を A より優先する"""
    def ok(c):
        return c not in g.index or (g.loc[c, "grade"] != "C" and g.loc[c].get("drop") != "個別の悪材料")
    cs = [c for c in focus.index if ok(c)]
    order = {c: i for i, c in enumerate(focus.index)}
    tier = focus["tier"] if "tier" in focus.columns else pd.Series(0, index=focus.index)
    return sorted(cs, key=lambda c: (tier[c], 0 if c in g.index and g.loc[c, "grade"] == "A" else 1, order[c]))[:n]


SHORT_NOTE = ("<b>選び方</b>: ①ランキング(期待スコア)60位以内 ②巻き添え安の条件(黒字・割安度が上位30%・直近1か月で市場以上に下落など) "
              "③ Claude の調査で C(避けたい)と「個別の悪材料で下げた」を外し、A を優先、残りは期待スコア順。"
              "①②の検証(2019〜2026年): 上位5銘柄は3か月後に全銘柄平均より <b>+3.1%</b>、上がっていた割合 <b>65%</b>、-30%以下 0.8%。2026年はマイナス(-2%)。"
              "翌営業日の寄り付きで買い、<b>約3か月保有</b>。")
LONG_NOTE = ("<b>選び方</b>: ①清原式(ネットキャッシュ比率1以上の黒字企業) ②期待スコアの高い順 ③ Claude の評価で C と「個別の悪材料」を外し、A を優先。"
             "①②の検証(2019〜2025年、5銘柄): 全銘柄平均より 1年後 <b>+12.5%</b>(上がっていた割合 78%、7年中6年で上回る)、2年後 <b>+38%</b>。"
             "途中で-50%以下まで下げたのは0.7%。<b>1年以上の保有</b>が前提。検証期間は割安株・PBR改善の追い風が強かった時期なので、同じ成績が続くとは限りません。")

LONG_NOTE_G = ("<b>選び方</b>: ①清原式(ネットキャッシュ比率1以上の黒字企業) ②決算短信の会社予想が増益(今期の営業利益の予想が前期より10%以上多い、"
               "または前期の減益から増益予想に転換)の銘柄を先に、期待スコアの高い順。足りなければ残りの清原式から補う "
               "③ Claude の評価で C と「個別の悪材料」を外し、A を優先。"
               "①②の検証(2019〜2025年、5銘柄、上場廃止した銘柄を含み配当は含まない): 全銘柄平均より 1年後 <b>+16.8%</b>"
               "(会社予想を使わない場合 +9.6%。7年すべてで上回る)、2年後 <b>+39%</b>。"
               "ただし会社予想を使わない場合との差は偶然の可能性を消しきれず(t 1.4)、条件も結果を見て決めたものなので、2026年11月以降の答え合わせで確かめます。"
               "<b>1年以上の保有</b>が前提。検証期間は割安株・PBR改善の追い風が強かった時期なので、同じ成績が続くとは限りません。")

def _picks_block(title, focus, g, nm, rank_of, note, empty, label, gr, dr) -> list:
    out = [f"<h2>{title}</h2>"]
    if focus is None or not len(focus):
        return out + [f"<p class='note'>{empty}</p>"]
    items = "".join(f"<li><b>{rank_of(c)}位 {c} {html.escape(str(nm(c)))}</b> {gr(c)} "
                    + (f"確信度 {html.escape(str(g.loc[c, 'confidence']))} / 下げた理由: {dr(c)} — {html.escape(str(g.loc[c, 'summary']))}" if c in g.index else "まだ調査していません")
                    + "</li>" for c in final_picks(focus, g))
    crow = "".join(f"<tr><td>{rank_of(c)}</td><td>{c}</td><td class='name'>{html.escape(str(nm(c)))}</td><td>{gr(c)}</td><td>{dr(c)}</td>"
                   f"<td class='num'>{r['score']*100:.0f}</td><td class='num'>{r['RET1M']:+.0f}%</td><td class='num'>{_f(r['PER'])}</td><td class='num'>{_f(r['NCR'], '{:.2f}')}</td></tr>"
                   for c, r in focus.iterrows())
    return out + [f"<ol class='picks'>{items}</ol>", f"<p class='note'>{note}"
                  "Claude の評価は検証済みではありません(下の答え合わせで確かめていきます)。投資判断はご自身で。</p>",
                  f"<details><summary class='note'>候補 {len(focus)} 銘柄({label})</summary><div class='wrap'><table>"
                  "<tr><th>順位</th><th>コード</th><th>銘柄</th><th>Claude</th><th>下げた理由</th><th>期待スコア</th><th>1か月</th><th>PER</th><th>ネットキャッシュ比率</th></tr>"
                  + crow + "</table></div></details>"]


def candidates_table(focus: pd.DataFrame, g: pd.DataFrame, nm, rank_of, picked=()) -> str:
    """最終候補の元になった候補の一覧(最終候補に選ばれた行は色付き)"""
    has_g = "fc_g" in focus.columns
    def gr(c):
        return grade_cell(g, c)
    def dr(c):
        return html.escape(str(g.loc[c].get("drop", ""))) if c in g.index and pd.notna(g.loc[c].get("drop")) else "未調査"
    crow = "".join(f"<tr class='{'new' if c in picked else ''}'><td>{rank_of(c)}</td><td>{c}</td><td class='name'>{html.escape(str(nm(c)))}</td>{gr(c)}<td>{dr(c)}</td>"
                   f"<td class='num'>{r['score']*100:.0f}</td><td class='num'>{r['RET1M']:+.0f}%</td><td class='num'>{_f(r['PER'])}</td>"
                   f"<td class='num'>{_f(r['NCR'], '{:.2f}')}</td>{guide_td(r) if has_g else ''}<td>{'最終候補' if c in picked else ''}</td></tr>"
                   for c, r in focus.iterrows())
    return ("<div class='wrap'><table><tr><th>順位</th><th>コード</th><th>銘柄</th><th>Claude</th><th>下げた理由</th><th>期待スコア</th>"
            "<th>1か月</th><th>PER</th><th>ネットキャッシュ比率</th>" + ("<th>会社予想(営業利益)</th>" if has_g else "")
            + "<th>結果</th></tr>" + crow + "</table></div>")


def guide_text(r) -> str:
    """会社予想の短い説明: 「+15%(増益予想)」など。予想が無ければ「−」"""
    v = r.get("fc_g") if hasattr(r, "get") else None
    if v is None or pd.isna(v):
        return "−"
    tag = "増益予想に転換" if r.get("guide_turn") == 1 and r.get("guide_up") != 1 else ("増益予想" if r.get("guide_up") == 1 else ("増益予想に転換" if r.get("guide_turn") == 1 else ""))
    return f"前期比 {v*100:+.0f}%" + (f"({tag})" if tag else "")


def guide_td(r) -> str:
    cls = " class='num up'" if bool(r.get("guide", False)) else " class='num'"
    return f"<td{cls}>{html.escape(guide_text(r))}</td>"


def research_html(top: pd.DataFrame, g: pd.DataFrame, check: pd.DataFrame | None, nm, focus: pd.DataFrame | None = None,
                  rank_of=None, long: pd.DataFrame | None = None, with_picks: bool = True) -> str:
    """最終候補(3か月: ランキング × 巻き添え安 / 長期: 清原式 × 期待スコア)× Claude評価 + 候補一覧 + 調査の詳細 + 答え合わせ
    with_picks=False なら、最終候補の部分は出さない(ページの最初のカードで出すため)"""
    rank_of = rank_of or (lambda c: list(top.index).index(c) + 1)
    def gr(c):
        return f"<span class='g g{g.loc[c, 'grade']}'>{g.loc[c, 'grade']}</span>" if c in g.index else "<span class='g gB'>未</span>"
    def dr(c):
        return html.escape(str(g.loc[c].get("drop", ""))) if c in g.index and pd.notna(g.loc[c].get("drop")) else "未調査"
    out = []
    if with_picks:
        out += _picks_block("最終候補: 3か月保有(3〜5銘柄)", focus, g, nm, rank_of, SHORT_NOTE,
                            "今日は「ランキング60位以内 かつ 巻き添え安の条件」を満たす銘柄がありません。ランキング上位から、Claude の評価が A の銘柄を優先してください。",
                            "ランキング60位以内 × 巻き添え安の条件", gr, dr)
        out += _picks_block("最終候補: 長期保有(1年以上・清原式 × 期待スコア)", long, g, nm, rank_of, LONG_NOTE,
                            "今日は清原式の条件を満たす銘柄がありません。", "清原式の条件を満たす銘柄、期待スコア順", gr, dr)
    inr = [c for c in g.index if c in top.index or any(x is not None and c in x.index for x in (focus, long))]
    if not inr:
        out.append("<p class='note'>まだ定性調査の結果がありません。週1回、Claude が候補を調べて A/B/C と下げた理由を付けます。</p>")
        return "".join(out)
    rows = []
    for c in inr:
        x = g.loc[c]
        rows.append(f"<tr><td>{rank_of(c)}</td><td>{c}</td><td class='name'>{html.escape(str(nm(c)))}</td>"
                    f"<td><span class='g g{x['grade']}'>{x['grade']}</span></td><td>{html.escape(str(x['confidence']))}</td><td>{dr(c)}</td>"
                    f"<td>{x['date']:%m/%d}</td><td class='why'>{html.escape(str(x['summary']))}"
                    f"<div class='sec'>＋ {html.escape(str(x['good']))}<br>− {html.escape(str(x['risk']))}</div></td></tr>")
    out.append(f"<details class='about'><summary>Claude が調べた {len(rows)} 銘柄の評価と理由</summary><div class='wrap'><table>"
               "<tr><th>順位</th><th>コード</th><th>銘柄</th><th>評価</th><th>確信度</th><th>下げた理由</th><th>調査日</th><th>理由</th></tr>"
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
                   "<div class='wrap'><table><tr><th>評価</th><th>期間</th><th>件数</th><th>平均</th><th>全銘柄平均との差</th><th>上がった割合</th></tr>"
                   + "".join(res) + "</table></div>")
    return "".join(out)
