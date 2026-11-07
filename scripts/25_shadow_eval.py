"""並走の答え合わせ: reports/shadow_picks.csv(チャンピオンと各チャレンジャーが毎日選んだ上位5)の成績 → research/lab/shadow.md

    python scripts/25_shadow_eval.py

- 選んだ日の翌営業日の寄り付きで買い、63営業日(3か月)後の終値で売ったとする。まだ3か月たっていない分は最新の終値で途中経過
- 同じ日の対象銘柄全体(売買代金3千万円以上など、本番と同じ条件)の平均との差。手数料 往復0.2% を引く
- チャレンジャーとチャンピオンは「両方の記録がある日」だけで比べる
- ゲート2(本番に入れる条件の後半): 3か月たった日が60営業日以上あり、その平均でチャンピオン以上
"""
import sys

import _bootstrap  # noqa: F401
import numpy as np
import pandas as pd

from jpstocks.backtest import Market, clean_split_artifacts, eligible
from jpstocks.challenger import LEDGER
from jpstocks.config import ROOT
from jpstocks.data import load_prices

H, COST, NEED = 63, 0.002, 60
OUT = ROOT / "research" / "lab" / "shadow.md"
LEDGER = sys.argv[1] if len(sys.argv) > 1 else LEDGER   # 試験用に別のファイルも渡せる
from pathlib import Path
L = pd.read_csv(LEDGER, dtype={"code": str}, parse_dates=["date"]) if Path(LEDGER).exists() else pd.DataFrame()
if not len(L):
    OUT.write_text("# 並走の答え合わせ\n\nまだ記録がありません(reports/shadow_picks.csv)。\n", encoding="utf-8")
    raise SystemExit("記録がありません")
pr = load_prices()
pr = pr[pr["date"] >= L["date"].min() - pd.Timedelta(days=420)]   # 対象銘柄の条件に上場からの日数(260営業日)があるので、1年以上前から
m, _ = clean_split_artifacts(Market.from_long(pr))
el = eligible(m, 0.3)
dates = m.adj_close.index
px, ao = m.adj_close, m.adj_open
last = len(dates) - 1
rows = []
for d, g in L.groupby("date"):
    i = int(dates.searchsorted(d))
    if i >= last or dates[i] != d:
        continue
    j = min(i + H, last)
    ent, ex = ao.iloc[i + 1], px.iloc[j]
    r = ex / ent - 1
    um = r[el.iloc[i]].clip(-0.95, 10).mean()
    for model, gg in g.groupby("model"):
        rr = r.reindex(gg["code"])
        rows.append({"date": d, "model": model, "ret": rr.mean() - COST, "ex": rr.mean() - COST - um, "matured": i + H <= last, "n": int(rr.notna().sum())})
R = pd.DataFrame(rows)
if not len(R):
    OUT.write_text("# 並走の答え合わせ\n\nまだ翌営業日の株価がある記録がありません。\n", encoding="utf-8")
    raise SystemExit("答え合わせできる記録がまだありません")
champ = R[R["model"] == "champion"].set_index("date")


def summ(x: pd.DataFrame, ref: pd.DataFrame | None) -> dict:
    mt = x[x["matured"]]
    out = {"記録した日": len(x), "3か月たった日": len(mt), "3か月の全銘柄平均との差%": mt["ex"].mean() * 100 if len(mt) else np.nan,
           "途中経過も含む差%": x["ex"].mean() * 100}
    if ref is not None:
        xs = x.set_index("date")
        both = xs.index.intersection(ref.index)
        dd = xs.loc[both, "ex"] - ref.loc[both, "ex"]
        dm = dd[xs.loc[both, "matured"]]
        out["チャンピオンとの差%(3か月たった日)"] = dm.mean() * 100 if len(dm) else np.nan
        out["チャンピオンとの差%(途中経過も含む)"] = dd.mean() * 100 if len(dd) else np.nan
        out["ゲート2"] = "通過" if len(dm) >= NEED and dm.mean() >= 0 else f"未({len(dm)}/{NEED}日)"
    return out


S = {"champion(本番)": summ(R[R["model"] == "champion"], None)}
for model, x in R[R["model"] != "champion"].groupby("model"):
    S[model] = summ(x, champ)
T = pd.DataFrame(S).T


def to_md(t: pd.DataFrame) -> str:
    def f(c, v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return ""
        if c.endswith("日"):
            return str(int(v))
        return f"{v:+.2f}" if isinstance(v, float) else str(v)
    lines = ["| モデル | " + " | ".join(t.columns) + " |", "|" + "---|" * (len(t.columns) + 1)]
    return "\n".join(lines + [f"| {i} | " + " | ".join(f(c, v) for c, v in r.items()) + " |" for i, r in t.iterrows()])


md = ["# 並走の答え合わせ(チャンピオン vs チャレンジャー)", "",
      f"更新: {dates[-1].date()}(株価の最新日)。scripts/25_shadow_eval.py が作成。条件は research/lab/README.md。", "",
      "各モデルが毎日選んだ「3か月の最終候補」上位5(期待スコア60位以内 × 巻き添え安)を、翌営業日の寄り付きで買って3か月持った場合。"
      "全銘柄平均との差、手数料 往復0.2% を引いた値。途中経過は最新の終値で計算。", "",
      to_md(T), ""]
OUT.write_text("\n".join(md), encoding="utf-8")
print(T.to_string())
