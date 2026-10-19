"""爆ハネ/暴落の確率モデルを学習して models/jump_model.pkl に保存(月1回くらい実行)

    python scripts/20_train_jump_model.py

全期間の株価と財務データを使うので 5〜15分ほどかかります。
"""
import time

import _bootstrap  # noqa: F401

from jpstocks.config import setup_logging
from jpstocks.data import load_prices, load_universe
from jpstocks.jump import build_world, make_samples, save_model, train

log = setup_logging("train")
t0 = time.time()
uni = load_universe()
w = build_world(load_prices(), uni, since="2016-10-01")   # 財務データ(EDINET)がある期間
log.info(f"特徴量を作成 ({time.time()-t0:.0f}秒)")
S = make_samples(w)
log.info(f"学習サンプル {len(S):,} 件 / {S['date'].min().date()} 〜 {S['date'].max().date()}")
b = train(S)
save_model(b)
log.info(f"保存しました: models/jump_model.pkl  (爆ハネの平均 {b['base_jump']*100:.1f}% / 暴落の平均 {b['base_crash']*100:.1f}%)  {time.time()-t0:.0f}秒")
