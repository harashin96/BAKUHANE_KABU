"""研究: 株価・出来高だけで作る古典的な戦略の検証(買いのみ、N銘柄に等金額、コスト込み)

    python scripts/10_research_price.py
    python scripts/10_research_price.py --min-value 5 --n 100

基準 = 同じ流動性条件を満たす全銘柄に等金額で投資した場合。直近1年は「確認」として別に表示。
"""
import _bootstrap  # noqa: F401

import argparse

import numpy as np
import pandas as pd

from jpstocks.backtest import Market, benchmark, eligible, perf, run_portfolio
from jpstocks.data import load_prices

ap = argparse.ArgumentParser()
ap.add_argument("--min-value", type=float, default=1.0, help="過去20日の売買代金の中央値(億円)の下限")
ap.add_argument("--n", type=int, default=30)
ap.add_argument("--cost-bp", type=float, default=15)
args = ap.parse_args()

m = Market.from_long(load_prices())
el = eligible(m, min_value_oku=args.min_value)
px = m.adj_close
r1 = px.pct_change(fill_method=None)
bm = benchmark(m, el)
ho = bm.index[-1] - pd.Timedelta(days=365)
S = {
    "短期の戻り 5日(週次)": (-(px / px.shift(5) - 1), 5),
    "短期の戻り 20日(月次)": (-(px / px.shift(20) - 1), 20),
    "モメンタム 12-1か月(月次)": (px.shift(21) / px.shift(252) - 1, 20),
    "モメンタム 6か月(月次)": (px / px.shift(126) - 1, 20),
    "低ボラ 60日(月次)": (-r1.rolling(60).std(), 20),
    "52週高値への近さ(月次)": (px / px.rolling(252).max(), 20),
    "小型(売買代金が小さい)(月次)": (-m.value.rolling(60).median(), 20),
}
b1, b2 = perf(bm[bm.index < ho]), perf(bm[bm.index >= ho])
print(f"基準: 研究期間 年率{b1['年率%']:.1f}% シャープ{b1['シャープ']:.2f} 最大DD{b1['最大DD%']:.0f}% | 直近1年 {b2['年率%']:.1f}%")
rows = []
for name, (sc, rb) in S.items():
    res = run_portfolio(m, sc, el, n=args.n, rebalance=rb, cost_bp=args.cost_bp)
    ex = res["net"] - bm.reindex(res.index)
    d, h = res.index < ho, res.index >= ho
    a, b = perf(res["net"][d]), perf(res["net"][h])
    rows.append({"戦略": name, "年率%": a["年率%"], "シャープ": a["シャープ"], "最大DD%": a["最大DD%"],
                 "基準との差%": ex[d].mean() * 252 * 100, "t値": ex[d].mean() / ex[d].std() * np.sqrt(d.sum()),
                 "直近1年%": b["年率%"]})
print(pd.DataFrame(rows).round(2).to_string(index=False))
